# Routing snapshots

Shaurya Execution consumes an immutable, date-stamped routing snapshot and never guesses a Kotak
token or trading symbol. The offline exporter is `execution/ops/export_routing_snapshot.py`. It uses
the public `shaurya.contracts` master parsers and public `shaurya.data` same-day indexes; it has no
broker client, credential input, capture function, or network operation.

## Inputs

Supply absolute paths to a Dhan compact master, a Kotak NSE F&O master, and a requested-universe
JSON document. The requested-universe schema is `execution/ops/routing_universe_schema_v1.json` and
contains schema version `1.0.0`, the trading date, explicit Dhan and Kotak master as-of dates, and a
unique nonempty list of canonical NSE F&O future/option IDs. All three dates must equal the explicit
`--trading-date`; dates are never inferred from mtime, a filename, symbol similarity, or expiry
proximity.

Inputs must be regular, non-symlink, current-user-owned files with no group/other write permission.
The exporter binds their exact bytes by SHA-256, parses private `0600` copies in the protected
output directory, and detects replacement of the originals before publishing. It rejects
malformed CSV structure, missing required columns, duplicate mappings, incomplete joins, unsupported
instruments, fractional/nonpositive lot or tick values, invalid routes, and duplicate token or
segment/symbol routes. Unrequested mappings do not enter the output.

Example invocation from the repository root, using the Data dependency environment but no network:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=data/src \
python execution/ops/export_routing_snapshot.py \
  --dhan-master /protected/non-secret/dhan-master.csv \
  --kotak-master /protected/non-secret/kotak-master.csv \
  --universe /protected/non-secret/requested-universe.json \
  --snapshot /protected/output/routing_snapshot.json \
  --manifest /protected/output/routing_manifest.json \
  --trading-date 2026-08-27
```

The exporter never accepts a URL, credential, token file, or broker session argument.

## Output and integrity

The output directory must already exist, be owned by the current user, have mode `0700`, resolve
without symlinks, and contain neither target. Snapshot and manifest must be absolute sibling paths.
Both leaf names are restricted to portable ASCII filename characters. Outputs are bounded to 16
MiB each and are canonical UTF-8 JSON with a final newline and mode `0600`.

`routing_snapshot_schema_v1.json` defines the sorted records and normalized provenance. Each record
contains only canonical instrument ID, exact Kotak token, segment, trading symbol, positive integral
lot size, and positive integral tick size in paise. Provenance contains broker roles and input
digests, never absolute source paths. `routing_manifest_schema_v1.json` binds the snapshot filename,
digest, byte length, record count, date, exporter version, universe digest, and source digests.

Temporary files are created and fsynced in the destination directory, read back, validated, and
installed without overwrite. The snapshot is installed before the manifest, which acts as the
completion marker. A crash can therefore leave a detectable partial pair; the exporter refuses such
state instead of silently repairing or deleting evidence. An already-existing byte-identical,
mode-correct pair is an idempotent success. Any differing, symlinked, partial, unsafe, or concurrently
replaced target is refused.

Runtime consumers must validate both strict schemas, snapshot filename, date, byte length, count,
SHA-256, source digests, sort order, and uniqueness before exposing any lookup. Any stale, missing,
partial, malformed, duplicate, substituted, or tampered artifact means `NO ORDER`.

## Hermetic test

Run the standard-library test with bytecode disabled and Data’s source package explicitly visible:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=data/src \
python -m unittest -v execution/tests/routing/test_routing_exporter.py
```

If the base interpreter does not already contain Data’s declared runtime dependencies, invoke the
same `unittest` command through an offline Data environment located under `/private/tmp`; do not
create an environment or dependency cache inside the repository.

CTest registers this suite as `execution.routing_exporter`. Configure
`SHAURYA_ROUTING_TEST_PYTHON` with the absolute path of an interpreter containing Data's runtime
dependencies; the cache value is machine-local and no personal interpreter path belongs in source.
