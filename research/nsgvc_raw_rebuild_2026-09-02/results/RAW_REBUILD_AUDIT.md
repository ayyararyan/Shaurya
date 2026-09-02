# NSGVC Independent Raw Rebuild Audit

This run rebuilt the NSGVC research chain from the consolidated NIFTY spot and option ZIPs, while preserving the package's frozen model and gate definitions.

- Rebuilt spot rows: 423,391
- Rebuilt 09:20 option rows: 34,178
- Frozen final-model training rows: 726
- Rebuilt RR400 cutoff: 0.027081006247852 (2.708101 vol points)
- Final trades: 56
- Mean net P&L at 6 points cost: 21.847314 option points
- Win rate: 58.928571%
- Total at the package's normalized 65-unit lot: INR 79,524.224000

Exact keyed comparisons are recorded in `raw_rebuild_audit.json`. A zero unmatched-row count and numerical differences near floating-point precision establish agreement with the frozen package.
