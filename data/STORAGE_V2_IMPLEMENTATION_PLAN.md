---
title: Storage V2 implementation
status: done
baseline_commit: a50981c5be19f581b8df26b1107efd6ae0392858
---

# Storage V2 implementation plan

## Verified starting point

- Production placement is the fail-closed daily archive
  `/Volumes/Aryan/NSE/YYYY-MM-DD/{raw,metadata,indexes,derived}`.
- New capture currently opens one `JsonlTapeWriter`; `DataCatalog`, `ArtifactManifest`, and the seek
  index also persist JSON/JSONL. `DatasetHandle` version 1 assumes one `tape_path`.
- `DataAccess` is already the public boundary, but active Research code still inspects tape/index
  paths or imports JSONL readers in `research/source.py`, dashboard entry points, the live rolling
  tools, and the full-session controller.
- Historical reports, fixtures, Research result artifacts, execution contracts, instrument-master
  manifests, and scratch outputs use JSON for purposes other than production raw market-event
  persistence. They are not a reason to rewrite immutable evidence or unrelated outputs.
- The prompt-listed `DAT-ACCESS-ARCHITECTURE-2026-08-21.md` was intentionally consolidated into
  `DAT.md` on current GitHub `main` and is not present in this checkout.

## Persistence inventory and treatment

| Class | Current examples | Storage V2 treatment |
|---|---|---|
| Raw market events | `tape_*.jsonl`, optional `.jsonl.gz` | New capture uses immutable segmented Parquet; legacy files remain read-only |
| Lifecycle/catalogue metadata | `datasets.jsonl`, `manifest_*.jsonl` | New events are atomically published immutable Parquet fragments |
| Integrity/index metadata | `*.index.json`, hashes in handles | Parquet footer statistics plus per-segment metadata and SHA-256; legacy indexes retained |
| Operational diagnostics | capture metrics and quality JSON | New Data capture emits typed Parquet event fragments; explicit CLI JSON output remains allowed |
| Generated Research output | reports, ledgers, dashboard cells, result JSON/JSONL | Out of raw-storage scope; preserve established reproducibility formats |
| Historical/legacy evidence | retained tapes, reports, fixtures and command examples | Never rename, rewrite, delete, or mislabel; use compatibility adapters |

## Ordered implementation

1. Add versioned Arrow schema and lossless `TapeRow` conversion, including decimal prices,
   timezone-aware timestamps, typed nested ladders, enums, flags, and schema-evolution checks.
2. Add a bounded segmented writer with row/time/estimated-size rotation, `.partial` staging,
   footer/schema/count validation, fsync, atomic rename, immutable human-readable filenames,
   per-segment hashes, and recovery inventory.
3. Introduce version-2 `DatasetHandle` contracts with a human dataset name, collision-resistant
   internal ID, ordered segments, storage/schema versions, dataset digest, and version-1 adapters.
4. Replace new catalogue writes with immutable Parquet lifecycle-event fragments. Retain a
   read-only JSONL catalogue loader and use atomic claim files for cross-process acquisition.
5. Change `DataCaptureSession` and capture entry points so no new raw JSON/JSONL writer is opened.
   Publish closed segments incrementally, and publish completion only after final validation.
6. Make `DataAccess` replay, filtering, validation, active following, and conversion dispatch on
   storage format. Reject partial, unpublished, unsupported, inconsistent, or hash-mismatched data.
7. Extend explicit legacy adoption with dry-run/conversion reports, source-state classification,
   semantic row digest verification, preservation checks, and resume-safe idempotence.
8. Migrate active Research consumers to format-neutral replay/follow/validation. Keep explicitly
   historical tape-path scripts reproducible through legacy adoption rather than altering claims.
9. Add CLI list/inspect/validate/preview/export/legacy-convert commands, tests for the required
   failure modes and boundaries, and a synthetic benchmark written only under `/private/tmp`.
10. Update root, Data, Research, architecture, and operational documentation; run lint, mypy, and
    tests for both projects; review and explicitly stage safe paths before pushing.

## Acceptance boundary

Passing software tests proves the storage implementation, not empirical completeness of any
retained capture. No production archive, broker session, credential, or real tape is accessed or
mutated by this work. A dataset becomes completed only from published closed segments whose
ordered hashes, row counts, coverage, sequence continuity, schema, and dataset digest validate.

## Suggested Review Order

**Storage and lifecycle boundary**

- Start with the format-neutral capture, replay, validation, and migration authority.
  [`access.py:95`](src/shaurya/data/access.py#L95)

- Review bounded immutable segment publication and recovery behavior.
  [`parquet.py:364`](src/shaurya/data/parquet.py#L364)

- Inspect digest-chained catalogue events, transition checks, and acquisition claims.
  [`catalog.py:342`](src/shaurya/data/catalog.py#L342)

- Confirm versioned handles preserve legacy meaning while governing Parquet datasets.
  [`data.py:214`](src/shaurya/contracts/data.py#L214)

**Legacy safety and downstream migration**

- Verify completion requires lifecycle-manifest evidence bound to the exact legacy tape hash.
  [`access.py:421`](src/shaurya/data/access.py#L421)

- Check active Research consumption now streams exclusively through DataAccess.
  [`cks_l1_ofi_scan.py:148`](../research/scripts/cks_l1_ofi_scan.py#L148)

- Confirm D49 accepts active segmented datasets and retains explicit legacy compatibility.
  [`ofi_response_surface.py:50`](../research/src/shaurya/cli/ofi_response_surface.py#L50)

**Acceptance evidence**

- Review field fidelity, rotation, recovery, filtering, lifecycle, and migration fixtures.
  [`test_parquet_storage.py:146`](tests/test_parquet_storage.py#L146)

- Review real concurrent acquisition exclusion and orphan lifecycle coverage.
  [`test_data_access.py:166`](tests/test_data_access.py#L166)

- Read benchmark limits and the measured storage trade-offs last.
  [`ADR-0001-SEGMENTED-PARQUET-STORAGE.md:114`](ADR-0001-SEGMENTED-PARQUET-STORAGE.md#L114)
