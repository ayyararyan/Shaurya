# D41 Report — Mid-Return Lags and CCZ OFI Are Complementary

**Run:** `X-D41-MID-LAG-OFI-2026-08-20`
**Claim:** `EF-11/H1`
**Registration commit:** `4751d1a35ead6f15e6a3c6a9bf2b5819b90ccb87`
**Implementation commit:** `a512fbe04bc32ba8e3fb2af0c5a426fa77fbff02`

## Owner summary

The result is clean. **Past mid returns are not a useful standalone forecast on today's saved
tape.** Their seven-lag model has roughly zero OOS R² at every horizon and is never significant
after horizon adjustment.

**OFI is better on point accuracy:** OFI alone has higher OOS R² than the lag bank in all 35
OFI-window × future-horizon cells. More importantly, OFI is not a disguised past-return signal.
After the complete lag bank is already in the model, adding OFI raises OOS R² in **35/35 cells**,
and every increment survives the full 35-cell Clark--West/Holm family.

The reverse incremental question is also informative. At the pre-named 10-second OFI window,
adding return lags raises OOS R² at every future horizon and survives the seven-horizon
Clark--West/Holm family every time. The union is therefore the best model: OFI carries most of the
standalone forecast content, while past returns add a smaller but distinct correction once OFI is
known.

**Bottom line:** neither variable is redundant. Use **CCZ OFI + the return-lag bank**, not lagged
returns instead of OFI and not OFI with the price path discarded.

## Direct answers

1. **Do mid-return lags predict future mid moves?** Not reliably by themselves. Lag-bank OOS R²
   ranges from −0.615% to +0.438%; all seven Holm-adjusted predictiveness p-values are 1.0.
2. **Are mid-return lags more accurate than OFI alone?** No. OFI has the higher point OOS R² in
   35/35 cells. The direct non-nested Diebold--Mariano differences do not survive adjustment, so
   the formal evidence is consistent point ranking rather than a rejected equal-loss null.
3. **Does OFI add after controlling for mid-return lags?** Yes. The increment is positive and
   Clark--West/Holm significant in 35/35 cells. At the primary 10-second OFI window it adds
   0.775–5.545 OOS-R² percentage points, depending on the future horizon.
4. **Is one of OFI and current return redundant?** No. At the primary window, return lags add
   0.439–2.881 points over OFI and are significant at all seven horizons. The largest absolute
   training correlation between any lag and any OFI level is only 0.308.

## Construction check: OFI against the current return

This is the descriptive same-window relation, kept separate from every future forecast.

| Same window | OFI-alone OOS R² | Holm p |
|---:|---:|---:|
| 0.5 s | 1.3401% | 0.00761 |
| 1 s | 3.8203% | 0.00356 |
| 2 s | 7.9379% | 0.000232 |
| 5 s | 13.5842% | 0.000815 |
| 10 s | 19.2571% | 0.00130 |
| 30 s | 24.6372% | 0.00658 |

The same-window check passes at every declared window and rises with aggregation length. This
confirms that the CCZ construction explains the current move; it is not used as evidence about
future returns.

## Primary future comparison: trailing 10-second CCZ OFI

All values below are absolute held-out OOS R² except the two increment columns. `OFI +lags` is the
exact feature union; no state control or other fitted benchmark is present.

| Future horizon | Lag bank | OFI alone | OFI + lags | OFI increment over lags | Lag increment over OFI | CW p: OFI increment | CW p: lag increment |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.5 s | 0.1157% | 0.4520% | **0.8905%** | +0.7748 pp | +0.4385 pp | 9.34e-8 | 5.62e-6 |
| 1 s | 0.1275% | 0.7277% | **1.2755%** | +1.1480 pp | +0.5478 pp | 2.70e-8 | 4.03e-7 |
| 2 s | 0.1284% | 1.2892% | **2.2514%** | +2.1230 pp | +0.9623 pp | 2.56e-8 | 1.01e-5 |
| 5 s | −0.1368% | 1.8697% | **2.9821%** | +3.1189 pp | +1.1124 pp | 3.45e-8 | 3.17e-5 |
| 10 s | 0.0046% | 2.0649% | **4.2960%** | +4.2914 pp | +2.2311 pp | 2.70e-8 | 8.47e-6 |
| 20 s | 0.4380% | 2.0482% | **4.9297%** | +4.4917 pp | +2.8815 pp | 1.14e-7 | 4.16e-5 |
| 30 s | −0.6151% | 3.0028% | **4.9301%** | +5.5452 pp | +1.9272 pp | 2.56e-8 | 4.16e-5 |

The direct lag-versus-OFI Diebold--Mariano p-values after the seven-horizon adjustment range from
0.120 to 0.512. The nested Clark--West tests are decisive because they ask the sharper questions:
what does OFI add once lags are already present, and what do lags add once OFI is present?

## Past-return models by future horizon

The fixed lag bank contains trailing returns at 0.5/1/2/5/10/20/30 seconds. Its predictiveness
test uses a Newey--West lag long enough to cover the 30-second history and target overlap.

| Future horizon | Lag-bank OOS R² | Best single lag | Best single-lag OOS R² | Holm p |
|---:|---:|---:|---:|---:|
| 0.5 s | 0.1157% | 0.5 s | 0.1917% | 1.0 |
| 1 s | 0.1275% | 0.5 s | 0.1953% | 1.0 |
| 2 s | 0.1284% | 2 s | 0.1826% | 1.0 |
| 5 s | −0.1368% | 20 s | 0.3113% | 1.0 |
| 10 s | 0.0046% | 10 s | 0.4140% | 1.0 |
| 20 s | 0.4380% | 10 s | 0.4891% | 1.0 |
| 30 s | −0.6151% | 10 s | 0.1467% | 1.0 |

## Complete OFI-window × future-horizon surface

Columns are future horizons 0.5/1/2/5/10/20/30 seconds. Rows are OFI accumulation windows.

### OFI alone — absolute OOS R²

| OFI window | 0.5 s | 1 s | 2 s | 5 s | 10 s | 20 s | 30 s |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.5 s | 0.2123% | 0.2711% | 0.5432% | 0.8832% | 0.8898% | 0.7922% | 0.7492% |
| 1 s | 0.2401% | 0.4158% | 0.8601% | 1.3195% | 1.3454% | 1.2364% | 1.1126% |
| 2 s | 0.4076% | 0.6631% | 1.1764% | 1.8449% | 1.9125% | 1.7198% | 1.6079% |
| 5 s | 0.4922% | 0.8116% | 1.4951% | 2.4137% | 2.4586% | 2.3703% | 2.3808% |
| 10 s | 0.4520% | 0.7277% | 1.2892% | 1.8697% | 2.0649% | 2.0482% | **3.0028%** |

### OFI plus lag bank — absolute OOS R²

| OFI window | 0.5 s | 1 s | 2 s | 5 s | 10 s | 20 s | 30 s |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.5 s | 0.4680% | 0.4933% | 0.7688% | 0.8706% | 1.0307% | 1.3648% | 0.2555% |
| 1 s | 0.5334% | 0.6576% | 1.1494% | 1.4631% | 1.6485% | 2.0121% | 0.7828% |
| 2 s | 0.7700% | 0.9914% | 1.7137% | 2.2697% | 2.5931% | 2.8970% | 1.6345% |
| 5 s | 0.9226% | 1.3736% | 2.3436% | 3.0453% | 3.8293% | 4.4740% | 3.1694% |
| 10 s | 0.8905% | 1.2755% | 2.2514% | 2.9821% | 4.2960% | 4.9297% | **4.9301%** |

### OFI's increment over the fixed lag bank

| OFI window | 0.5 s | 1 s | 2 s | 5 s | 10 s | 20 s | 30 s |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.5 s | +0.3523 | +0.3658 | +0.6404 | +1.0075 | +1.0261 | +0.9268 | +0.8706 |
| 1 s | +0.4177 | +0.5301 | +1.0210 | +1.5999 | +1.6439 | +1.5741 | +1.3979 |
| 2 s | +0.6543 | +0.8639 | +1.5853 | +2.4065 | +2.5885 | +2.4591 | +2.2496 |
| 5 s | +0.8069 | +1.2461 | +2.2152 | +3.1821 | +3.8247 | +4.0360 | +3.7845 |
| 10 s | +0.7748 | +1.1480 | +2.1230 | +3.1189 | +4.2914 | +4.4917 | +5.5452 |

Entries are OOS-R² percentage points. All 35 are positive and all 35 survive the full 35-cell
Clark--West/Holm family. Lags add over OFI in 32/35 cells and survive the full surface adjustment
in 28/35; the pre-named 10-second OFI row is positive and significant in 7/7.

## Method and support

- Future target: displayed-mid return from `t+0.5 s` to `t+0.5 s+h`.
- Lag features: displayed-mid returns ending at `t`, over 0.5/1/2/5/10/20/30 seconds.
- OFI features: ten separate D37 CCZ depth-scaled rank-keyed levels over each declared window.
- Models: lag bank, OFI alone, exact union. No spread, depth, microprice or other fitted model.
- Chronological split: 57,537 base training anchors, 131 embargoed, 24,528 base test anchors;
  30.5-second embargo. Exact scored support falls from 24,523 to 24,402 as the future horizon
  lengthens.
- Ridge penalties, feature centres/scales and target mean are selected on training data only.
- Inference: Newey--West overlapping-loss tests; two-sided Diebold--Mariano for lag versus OFI;
  one-sided Clark--West for the two nested incremental questions; Holm control across the primary
  seven horizons and the full 35-cell surface.
- Effective sample sizes and approximate pre-declared MDEs are recorded per test in the full and
  compact artifacts.

## Reproducibility and verification

- Tape SHA-256: `93456eda4de33cc22fc1d9d3dc8fb5ca7a7bb8eab7108e3c0ef8859a97759a43`
- Full artifact SHA-256: `19d1ee96f118e01061bbb13e148a16f892484a758199f7e16f9c5ce6aa072b04`
- Compact artifact SHA-256: `96a96f557b00e4c99951c8355a147646179705dc85b105ffda9da47a26c7bb9a`
- Focused D39/D40/CCZ/D41 tests: 30 passed.
- Whole repository: 679 passed; 11 known ridge-zero-singular-value warnings.
- Whole-repository Ruff: passed.
- Strict mypy: 66 source files passed.
- Compileall and artifact-to-compact parity: passed.
- Complete axes, common row hashes, exact feature unions, Holm family fields and content hashes:
  passed.

Durable full artifacts:
`/Users/maheit/.openclaw/workspace/overnight-runs/d41-mid-lag-ofi-20260820/artifacts/`.

Committed machine summary: `docs/results/D41-MID-LAG-OFI-INCREMENTAL-2026-08-20.json`.

## Claim boundary and tomorrow

This is a retrospective partial-session exploration on today's saved tape. Tomorrow's locked D39
and D40 tests remain unchanged. After they finish, run D41 unchanged on the same untouched full
session; that is the clean test of whether the complementary OFI-plus-lag result reproduces.
