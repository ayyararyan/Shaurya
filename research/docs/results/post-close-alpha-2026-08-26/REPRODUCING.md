# Reproducing the 2026-08-26 post-close analysis

The replay command must point to the immutable catalog that contains
`sha-20260826T063840.939559Z-b7c47c19`. It refuses non-`COMPLETED` or invalidated handles and
rechecks the tape/index/manifest hashes before reading. Use a new empty derived output root; the
runner creates its result directory exclusively and has no rerun mode.

```bash
export PYTHONDONTWRITEBYTECODE=1
python scripts/post_close_alpha_research.py \
  --dataset-id sha-20260826T063840.939559Z-b7c47c19 \
  --catalog /path/to/immutable/metadata/datasets.jsonl \
  --output-root /path/to/separate/derived
```

Let `PANEL` and `SCREENING_RESULTS` refer to `derived_feature_panel.csv.gz` and
`research_results.json` in the newly created derived directory. Then produce the aggregate
correlation and final chronological-validation outputs:

```bash
python scripts/compute_feature_correlations.py \
  --panel "$PANEL" \
  --results "$SCREENING_RESULTS" \
  --output feature-correlations.json

python scripts/validated_ridge_analysis.py \
  --panel "$PANEL" \
  --results "$SCREENING_RESULTS" \
  --output validated-ridge-results.json
```

No command authenticates to Dhan, accesses account/order APIs, changes raw/catalog data, starts a
collector, or invokes D51. The checked-in JSON files are aggregate outputs only; the raw tape,
derived panel, logs, credentials, environment files, and temporary files are deliberately absent.
