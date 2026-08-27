# Shaurya Research

Shaurya Research is the independently installable analysis project. It contains order-book and
OFI features, volatility surfaces, correlations, predictive tests, walk-forward experiments,
research dashboards, daily pipelines, and persisted research evidence. Its only market-data
dependency is the public catalogue and replay interface supplied by Shaurya Data.

It contains no broker connectivity, order placement, execution engine, or live-trading strategy.

## Install and test

From the repository root, enter the Research project before running its tools so test discovery
and relative script imports stay scoped to Research:

```bash
cd research
uv sync --extra dev
uv run pytest
```

The sibling `data/` project is installed through Research's declared `shaurya-data` dependency;
the Dhan collector is not imported by Research.

## Run research for a dataset or date

The quality-aware daily pipeline waits for a completed catalogue handle, verifies lifecycle,
schema, hashes, ordered logical replay, and coverage through `DataAccess`, then writes its report
and machine-readable results to the requested output directory. Research does not open Parquet or
legacy JSONL paths directly:

```bash
uv run shaurya-daily-research \
  --catalog /archive/NSE/2026-08-26/metadata/datasets \
  --dataset-id ds-example \
  --output-root /absolute/path/to/research-results
```

To resolve the latest completed dataset for a trading date through the same catalogue interface:

```bash
uv run shaurya-daily-research \
  --catalog /archive/NSE/2026-08-26/metadata/datasets \
  --date 2026-08-26 \
  --output-root /absolute/path/to/research-results
```

The generated `FINAL_MEMO.md` is the daily report. Existing focused commands remain available,
including `shaurya-ofi-dashboard`, `shaurya-surface-dashboard`,
`shaurya-live-ofi-studies`, `shaurya-rolling-c8`, and
`shaurya-feature-selection-experiment`; use each command's `--help` for its exact inputs.

Curated research provenance lives under `docs/results/`. Large or local generated artifacts must
remain outside Git.

Historical scripts that deliberately pin immutable JSONL evidence remain supported through the
legacy compatibility lane and retain their original provenance. Current capture, dashboards,
rolling studies, post-close research, and full-session OFI orchestration resolve dataset IDs and
consume format-neutral logical rows. A passing storage/software test is not evidence that a market
session is complete; the completed catalogue state and the pipeline's domain coverage gates are
both required.

## High-frequency v2 registry bundle

`HIGH_FREQUENCY_REGISTRY_BINDING` binds `microstructure_features_v2`,
`microstructure_targets_v2`, `alpha_hypotheses_v2`, and `alpha_research_policy_v2`. Select those
versions explicitly for the 2026-08-27 construction freeze; v1 remains the legacy default for
backward-compatible historical workflows. The v2 policy keeps three-session candidates in shadow
status and quarantines the non-transportable/replication-only fields from automatic live weight.
