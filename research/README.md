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

The quality-aware daily pipeline waits for a completed catalogue handle, verifies its manifest,
hashes, index, and coverage, then writes its report and machine-readable results to the requested
output directory:

```bash
uv run shaurya-daily-research \
  --catalog /Volumes/Aryan/NSE/2026-08-26/metadata/datasets.jsonl \
  --dataset-id sha-20260826T034500.000000Z-example \
  --output-root /absolute/path/to/research-results
```

To resolve the latest completed dataset for a trading date through the same catalogue interface:

```bash
uv run shaurya-daily-research \
  --catalog /Volumes/Aryan/NSE/2026-08-26/metadata/datasets.jsonl \
  --date 2026-08-26 \
  --output-root /absolute/path/to/research-results
```

The generated `FINAL_MEMO.md` is the daily report. Existing focused commands remain available,
including `shaurya-ofi-dashboard`, `shaurya-surface-dashboard`,
`shaurya-live-ofi-studies`, `shaurya-rolling-c8`, and
`shaurya-feature-selection-experiment`; use each command's `--help` for its exact inputs.

Curated research provenance lives under `docs/results/`. Large or local generated artifacts must
remain outside Git.
