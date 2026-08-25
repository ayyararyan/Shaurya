# Gap-open research workspace

This directory is a committed research record, despite its `scratch/` name. It contains the
analysis code, frozen test specifications, reports, audits, and compact result files behind the
gap-open work. Do not bulk-delete or regenerate it as ordinary temporary output.

## Where to start

- [`FINDINGS_SUMMARY.md`](FINDINGS_SUMMARY.md) summarizes the main findings and their limits.
- [`GAP_FILL_SIGNAL_MODULE_SPEC.md`](GAP_FILL_SIGNAL_MODULE_SPEC.md) describes the proposed
  module boundary.
- `GATE_A_*` covers the gap-fill put and its censoring, stop/target, and walk-forward checks.
- `GATE_B_*` covers continuation, structure choice, exits, volume/open-interest, and robustness.
- `FOLKLORE_BATTERY_*`, `NGE_*`, `RANGE_FORECAST_*`, `TAIL_CLIP_*`, and `VRP_*` group the other
  registered questions and their reports.

## File conventions

- `*.py` files are analysis or verification code.
- `*_SPEC.md` and similarly named specification files freeze a question before testing.
- `*_TEST.md`, research reports, and `FINDINGS_SUMMARY.md` explain results in human-readable form.
- `*_results.json`, audit JSON, and the retained text outputs are compact reproducibility artifacts.
- [`gate_b_structure_search.py.orig`](gate_b_structure_search.py.orig) is intentionally retained as
  the as-received, pre-patch baseline documented in
  [`GATE_B_STRUCTURE_SEARCH.md`](GATE_B_STRUCTURE_SEARCH.md); it is not an accidental editor backup.
- `FOLKLORE_BATTERY_RESULTS.md` is an intentional report alias written alongside
  `FOLKLORE_BATTERY_TEST.md` by `folklore_battery.py`.

Source market data and local model environments are external to this tree and ignored by Git.
