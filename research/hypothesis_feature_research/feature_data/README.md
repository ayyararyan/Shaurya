# Feature data

This directory stores small derived feature values only when their lineage and grain are known.
It never stores raw market tapes. At catalogue creation time no feature-value CSV was copied or
regenerated: the existing D51 derived tables remain immutable at their original paths and are
referenced from `manifest.csv` with size, row count, modification time, and SHA-256.

The minimum long-format schema for a future feature-value file is:

`as_of_date, session_date, event_timestamp, instrument, venue, feature_id, feature_value,
feature_version, source_dataset, source_test_or_pipeline, generated_at, code_revision,
quality_status`

Rules:

- `event_timestamp` is the market observation/anchor time; `generated_at` is provenance time.
- `feature_id` must resolve in `../features.csv`.
- `source_dataset` must be an immutable catalogue/dataset identity or a documented synthetic
  fixture. Cancelled or incomplete captures are never eligible sources.
- `quality_status` must state exclusions, partial support, or unvalidated status explicitly.
- A wide table is allowed only when its keys, common grain, feature columns, and provenance
  columns are documented in `manifest.csv`.
- Regeneration must be bounded, read-only with respect to source data, and must not call broker,
  credential, network, order, or live-routing paths.

See `../schemas/feature_data.schema.md` for the complete field contract.
