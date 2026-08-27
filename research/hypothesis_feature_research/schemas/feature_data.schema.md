# Feature-value and manifest schema

## Long-form feature values

Required provenance columns are `as_of_date`, `session_date`, `event_timestamp`, `instrument`,
`venue`, `feature_id`, `feature_value`, `feature_version`, `source_dataset`,
`source_test_or_pipeline`, `generated_at`, `code_revision`, and `quality_status`.

`event_timestamp` uses an ISO-8601 offset or an explicitly documented nanosecond epoch convention.
The file documentation must state timezone, keys, grain, ordering, duplicate policy, missing-value
encoding, and whether `feature_value` is numeric or categorical. Wide files must retain the same
provenance information and enumerate their feature columns.

## `manifest.csv`

Each row records stable artifact ID, repository-relative path, whether data is copied or referenced,
feature family, grain, schema summary, bytes, data-row count, coverage, UTC modification time,
SHA-256, producing pipeline, quality status, and notes. Checksums describe the referenced bytes;
they do not by themselves validate the economics or source completeness.
