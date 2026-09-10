# RV-V2 q Threshold Recalibration — 2026-09-10

## Decision

**Frozen operational q threshold: `0.825`**  
Sensitivity band: `0.80-0.85`  
RR400: diagnostic/regime state only; no master veto.

The score is the frozen RV-V2 variance ratio

\[
q=\widehat V_{10:00\rightarrow expiry}/\theta_{eSSVI}.
\]

This is a variance ratio. The volatility ratio `sqrt(q)` is not the gate.

## Strategy object

The threshold study uses the nearest-weekly NIFTY ATM short iron butterfly with 500-point wings. A potential entry is evaluated at the completed 10:00 IST bar. There is at most one new entry per expiry; when several origins satisfy a threshold, the earliest eligible origin is used.

Historical option prices are used only where the rolling ATM-relative archive identifies the traded structure cleanly: the exact 10:00 entry snapshot. Terminal expiry P&L is then identified from the bounded iron-fly payoff and the final NIFTY level:

`net P&L = entry credit - min(abs(expiry spot - centre), 500) - cost_points`.

The headline cost assumption is 2 structure points, with 0/4/6/8-point stress. The frozen RV coefficients are never refitted while thresholds are tested.

The live once-daily management rule remains a strict `abs(forward-centre) > 250` recenter check. Because a rolling ATM-relative historical file can change the fixed contract represented as spot moves, interim fixed-contract recenter marks are not used to select the q threshold. This prevents a convenient but invalid contract splice from contaminating calibration.

## Why the old 0.70 threshold cannot simply be reused

The new Day + Gamma-night forecast changes the q distribution materially. In the recalibration data the new q median is roughly 0.86-0.88 in ordinary 2023-2025 regimes, versus roughly 0.74 for the old NSGVC mapping. Carrying 0.70 forward would therefore create a much more restrictive strategy than the one originally studied.

## Grid search and failed mechanical optimum

The q grid was `0.40, 0.425, ..., 1.20`. A mechanical 2023-2024 development rule—maximize mean net return on max risk with at least 25 distinct expiry trades—selected `q=0.75`.

That value did **not** survive validation:

| Sample | Trades | Total P&L pts | Mean return on risk |
|---|---:|---:|---:|
| 2023-2024 | 34 | +1,440.40 | +0.2127 |
| 2025 | 17 | -497.25 | -0.0281 |
| 2026 Jan-May | 12 | -315.65 | -0.1291 |
| 2026 May-Aug | 3 | +87.05 | +0.1339 |

Accordingly `0.75` is rejected rather than promoted.

## Robust threshold band

The stable region was 0.80-0.85. Year-by-year return-on-risk shows why 0.825 is the robust centre:

| q | 2023 | 2024 | 2025 | minimum year |
|---:|---:|---:|---:|---:|
| 0.800 | +0.1503 | +0.1127 | +0.1226 | +0.1127 |
| **0.825** | **+0.1617** | **+0.1170** | **+0.1899** | **+0.1170** |
| 0.850 | +0.0298 | +0.0956 | +0.1643 | +0.0298 |

Thus 0.825 maximizes the worst 2023-2025 calendar-year mean return-on-risk among these stable candidates, while 0.85 noticeably degrades 2023 and 0.80 turns negative in both 2026 slices.

## Frozen 0.825 results

At 2 points of structure cost:

| Period | Trades | Total P&L pts | Mean P&L pts | Win rate | Mean R |
|---|---:|---:|---:|---:|---:|
| 2023 | 10 | +544.40 | +54.44 | 90.0% | +0.1617 |
| 2024 | 51 | +975.30 | +19.12 | 58.8% | +0.1170 |
| 2025 | 36 | +1,525.70 | +42.38 | 61.1% | +0.1899 |
| 2023-2025 pooled | 96 | +3,319.00 | +34.57 | 63.5% | +0.1606 |
| 2026 Jan-May | 16 | +406.25 | +25.39 | 62.5% | +0.1592 |
| 2026 May-Aug | 9 | +79.60 | +8.84 | 77.8% | +0.0162 |
| 2026 combined | 25 | +485.85 | +19.43 | 68.0% | +0.1077 |

Bootstrap 95% interval for pooled 2023-2025 mean R: approximately `[+0.0462, +0.2781]`. The 2026 sample is only 25 expiries, so its uncertainty is much larger.

## Cost stress

At q=0.825 the aggregate point P&L remains positive in every reported split through an 8-point structure-cost assumption:

| Cost pts | 2023-24 | 2025 | 2026 Jan-May | 2026 May-Aug |
|---:|---:|---:|---:|---:|
| 0 | +1,641.70 | +1,597.70 | +438.25 | +97.60 |
| 2 | +1,519.70 | +1,525.70 | +406.25 | +79.60 |
| 4 | +1,397.70 | +1,453.70 | +374.25 | +61.60 |
| 6 | +1,275.70 | +1,381.70 | +342.25 | +43.60 |
| 8 | +1,153.70 | +1,309.70 | +310.25 | +25.60 |

This is a stress diagnostic, not a claim that every live fill costs a fixed number of points.

## RR400

The old reference `RR400 <= 0.0270810062` was tested as a secondary veto at q=0.825. It improved the 2023-2025 calibration subset but reduced trade count from 96 to 38 and generated negative aggregate performance in the Jan-May 2026 diagnostic subset. Therefore no RR400 master veto is promoted. A new RR cutoff would require a separate pre-registered experiment.

## Inference / lookahead status

- Frozen RV coefficients are not refit during q calibration.
- Every score uses information available at the 10:00 origin.
- Only fully realized expiry outcomes enter historical P&L.
- May-August 2026 had already been examined to choose/freeze the RV architecture on QLIKE, but its option P&L and q thresholds had not been used in that choice. It is therefore conditional evidence, not a pristine joint model-selection holdout.
- The final 0.825 choice is adaptive because it was chosen after the 2023-24 mechanical optimum failed subsequent years. After this freeze, genuinely new market data are the clean prospective test.

## Frozen rule

```text
MODEL = RV-V2-DAY-GAMMA-ESSVI-2026-09-10
Q = forecast_integrated_RV / eSSVI_theta
ENTRY_OR_CONTINUE = Q < 0.825
RECENTER_CHECK = once daily at 10:00 IST
RECENTER = abs(forward - held_centre) > 250 points
WINGS = +/-500 points
RR400 = diagnostic only
```

Do not retune `0.825` from routine short-term P&L. Any change requires a versioned recalibration and forward/OOS evidence.
