# NIFTY 50 first-minute versus opening-window returns

**Exploratory scan using Dhan-derived NIFTY spot stamps stored in Still_Water's ATM/CALL minute files. No live API or order path was used.**

## Sample

The 66 manifest-selected files contain 497,023 minute rows from 2021-01-01T09:15:00+05:30 through 2026-05-14T15:29:00+05:30. Of 1,329 dated sessions, **1,320** have all required 09:15, 09:16, 09:17, 09:30 and 09:45 IST observations. 9 incomplete or special-evening sessions were excluded.

Returns use spot levels stamped at the named minute: `r1=09:16/09:15-1`, `r2=09:17/09:15-1`, and outcomes at 09:30/09:45. The gap split uses the previous available regular session's fixed 15:29 spot; flat means within ±5 bp.

## Requested correlations

| Predictor | Outcome | N | Pearson r | p | Spearman rho | p | Same sign |
|---|---|---:|---:|---:|---:|---:|---:|
| r1 | r_0915_0930 | 1320 | 0.265 | <0.001 | 0.316 | <0.001 | 62.8% |
| r1 | r_0915_0945 | 1320 | 0.244 | <0.001 | 0.278 | <0.001 | 61.1% |
| r2 | r_0915_0930 | 1320 | 0.379 | <0.001 | 0.414 | <0.001 | 63.8% |
| r2 | r_0915_0945 | 1320 | 0.311 | <0.001 | 0.336 | <0.001 | 62.6% |

These headline outcomes mechanically include the first one/two minutes. Positive correlation and 61–64% sign agreement therefore do not by themselves show that the early move predicts the *remaining* window.

## Non-overlapping continuation diagnostic

| Early move | Subsequent leg | Pearson r (p) | Spearman rho (p) | 1% winsor r | Same sign |
|---|---|---:|---:|---:|---:|
| r1 | r_after_r1_to_0930 | -0.101 (<0.001) | -0.006 (0.819) | -0.019 | 51.6% |
| r1 | r_after_r1_to_0945 | -0.050 (0.068) | 0.023 (0.409) | 0.002 | 52.9% |
| r2 | r_after_r2_to_0930 | -0.104 (<0.001) | -0.009 (0.757) | -0.039 | 50.7% |
| r2 | r_after_r2_to_0945 | -0.078 (0.005) | 0.007 (0.793) | -0.029 | 51.7% |

Raw Pearson suggests mild mean reversion in some cells, but Spearman is effectively zero, winsorized Pearson is near zero, and directional accuracy is only 50.7–52.9%. The raw Pearson result is tail-sensitive—4 June 2024 alone combines a +76 bp first minute with a -235 bp subsequent 09:16–09:30 leg.

## Gap-direction split

| Gap group | N | r1→total 09:30 Pearson/Spearman | r1→total 09:45 | r1→subsequent 09:30 Pearson/Spearman/sign | r1→subsequent 09:45 |
|---|---:|---:|---:|---:|---:|
| gap_down | 493 | 0.208/0.347 | 0.253/0.316 | -0.143/0.027/52.9% | -0.048/0.056/55.0% |
| flat_5bp | 111 | 0.481/0.391 | 0.420/0.352 | 0.127/0.113/55.0% | 0.124/0.058/50.5% |
| gap_up | 714 | 0.293/0.284 | 0.214/0.246 | -0.087/-0.045/50.3% | -0.071/0.006/52.0% |

The flat subgroup looks stronger in the overlapping statistic but has only 111 days. After removing overlap, no gap group shows a stable monotonic continuation effect; same-sign rates range from roughly 49% to 55%.

## Boundary robustness

Using 09:29/09:44 instead of the explicitly available 09:30/09:45 leaves the headline conclusion unchanged: Pearson correlations are 0.287, 0.236, 0.408, 0.307 for the same four cells.

## Verdict

**Not worth building a directional trading idea around in this form.** The first one/two-minute move is strongly correlated with the total 15/30-minute return, but mostly because that early move is part of the target itself. Once the overlapping minutes are removed, rank correlation and directional accuracy are indistinguishable from a useful continuation signal. The only visible raw Pearson mean reversion is tail-driven and unstable across years. A strategy would need a different conditioning variable—such as opening-auction imbalance, overnight news/gap size, breadth, or futures order flow—and prospective out-of-sample testing with costs.

## Caveats

- `spot` is a Dhan-derived underlying level embedded in rolling ATM option files, not a separately fetched NIFTY OHLC bar. The analysis treats each stamped value as the index level at that minute.
- Nine dates were excluded: three start at 09:16, four are Muhurat/evening sessions, one starts at 13:45, and one starts at 09:19.
- Ordinary correlation p-values are IID approximations and are unadjusted for serial dependence or the headline/subgroup multiple comparisons.
- The prior-close gap uses 15:29 consistently; it is a close proxy rather than an official exchange closing value.
