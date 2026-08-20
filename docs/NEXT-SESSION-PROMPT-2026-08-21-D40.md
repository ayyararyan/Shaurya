# Next-session prompt — validate the D40 displayed-mid horizon shape

First complete and report the already locked 2026-08-21 D39 run exactly as registered. Do not
change its model panel, horizons, reference-price ladder, sample gates or conclusions.

After D39 is complete, run the separately frozen D40 validation on the same untouched full-session
tape using `docs/D40-OFI-HORIZON-EXTENSION-SPEC-2026-08-20.md` and
`scripts/d40_ofi_horizon_extension.py`.

## Fixed model object

- Forecast displayed-mid returns only. Do not forecast last-trade-price returns.
- Use D39 competitor `C8` exactly: displayed spread, `log1p` level-one depth, and ten separate
  depth-scaled rank-keyed CCZ OFI levels.
- Use `M=10` and the trailing OFI window `(t−10 s,t]`.
- Keep the causal gap at 0.5 seconds.
- Evaluate horizons `10, 20, 30, 45, 60, 90, 120` seconds.
- Keep custom response horizons additive to the original D39 response map so the anchor universe
  and training boundary do not move.
- Use a chronological 70/30 split and an embargo of at least 120.5 seconds.
- Fit all scaling, target mean, ridge penalty and coefficients on training data only.

## What today's behavior was

The corrected 2026-08-20 partial-session extension produced absolute OOS R²:

- 10 s: 7.4037%
- 20 s: 15.7793%
- 30 s: −0.4698%
- 45 s: −8.8594%
- 60 s: −18.7876%
- 90 s: −23.0628%
- 120 s: −22.6148%

The tested peak was 20 seconds. The first decline was at 30 seconds, where raw predictive power
became negative and stayed negative through 120 seconds.

## Required validation report

Report only C8's absolute OOS R² at each horizon. Do not compare it with another fitted model or
an external benchmark. State explicitly:

1. whether the 10-to-20-second increase repeats;
2. which tested horizon has the maximum absolute OOS R²;
3. the first tested horizon at which R² declines;
4. whether R² becomes non-positive by 30 seconds;
5. whether it remains non-positive through 120 seconds; and
6. whether the complete horizon curve reproduces or rejects the 2026-08-20 shape.

Record the tape hash, code commit, split boundary, embargo, train/test row counts, row hashes and
full-artifact hash. Update the D40 report, compact result JSON, traceability matrix and changelog,
then commit and push the verified result to `ayyararyan/Shaurya`.

## After D39 and D40 — validate D41 unchanged

Only after both locked runs above are complete, apply
`docs/D41-MID-LAG-OFI-INCREMENTAL-SPEC-2026-08-20.md` and
`scripts/d41_mid_lag_ofi.py` to the same untouched full-session tape. Do not change D39 or D40 to
make room for it.

Keep the D41 object unchanged: future displayed-mid returns after a 0.5-second gap at
0.5/1/2/5/10/20/30 seconds; trailing displayed-mid return lags at
0.5/1/2/5/10/20/30 seconds; ten separate depth-scaled rank-keyed CCZ OFI levels over
0.5/1/2/5/10-second windows; and only the lag bank, OFI alone and their exact union. Preserve the
training-only ridge choices, common-row contract, 30.5-second embargo, HAC/Diebold--Mariano,
nested Clark--West and Holm families.

Validate the 2026-08-20 D41 finding: lag returns were weak alone; OFI had higher point OOS R² in
35/35 cells; OFI added beyond lags in 35/35; and at the pre-named 10-second OFI window the lags
also added at all seven horizons. Report whether each statement reproduces, with no order or
signal authority attached.
