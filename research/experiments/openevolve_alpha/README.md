# OpenEvolve alpha experiment

This experiment evolves a restricted numerical `alpha_score` function. Generated code cannot
read files, import modules, use the network, inspect dates, or access validation/final returns.
The cache contains only September 1, 2025 through June 30, 2026.

## Prepare

```powershell
uv sync --extra research
uv run shaurya-openevolve-alpha prepare `
  --index-zip NIFTY_1MIN_OHLC_2021-2026.zip `
  --cache scratch/openevolve-alpha/discovery.npz
```

## Run evolution

The custom runner uses the locally authenticated Codex CLI; no API key is required:

```powershell
uv run python experiments/openevolve_alpha/run_with_codex.py `
  --initial-program experiments/openevolve_alpha/initial_program.py `
  --evaluator experiments/openevolve_alpha/evaluator.py `
  --config experiments/openevolve_alpha/config.yaml `
  --output scratch/openevolve-alpha/run-001 `
  --iterations 100
```

The configuration uses GPT-5.6 Luna for breadth and GPT-5.6 Sol for depth. Each Codex subprocess
runs ephemerally in an empty temporary directory with a read-only sandbox. It receives the
OpenEvolve prompt but cannot inspect or edit this repository.

## Research discipline

OpenEvolve output is discovery material, not a profitable strategy. Select a small frozen set
from discovery before running a separate July 1-August 14 promotion test. Track the number of
programs evaluated and correct for selection. The August 17-21 slice must only be accessed by a
candidate that passes promotion. Actual trading additionally requires NIFTY futures data, basis,
fees, slippage, and fill assumptions.

Promote exactly one frozen discovery winner:

```powershell
uv run shaurya-openevolve-alpha promote `
  --program experiments/openevolve_alpha/discovery_best_20.py `
  --index-zip NIFTY_1MIN_OHLC_2021-2026.zip `
  --cache scratch/openevolve-alpha/discovery.npz
```

Do not repeatedly promote new winners against the same validation interval. That converts the
validation interval into training data and invalidates its p-value.
