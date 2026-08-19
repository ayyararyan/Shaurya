# Compact model table — `X-SURFACE-FUT5-20260819-06`

Permanent status: exploratory; `confirmatory_eligible=false`. All rows use one identical test set
of 751 observations and score against the future target's training mean.

| Model | Raw features | Alpha | OOS R² | RMSE ticks | Half 1 R² | Half 2 R² |
|---|---:|---:|---:|---:|---:|---:|
| N | 0 | — | 0.000000 | 25.799867 | — | — |
| S | 72 | 100 | −0.002424 | 25.831120 | −0.008780 | +0.009937 |
| SQ | 95 | 100 | −0.113302 | 27.222250 | −0.065209 | −0.206833 |
| L | 28 | 100 | −0.007421 | 25.895418 | −0.000883 | −0.020135 |
| O | 6 | 100 | −0.020068 | 26.057463 | −0.010699 | −0.038290 |
| LO | 34 | 100 | −0.029047 | 26.171892 | −0.014875 | −0.056609 |
| LOS | 106 | 100 | −0.060774 | 26.572286 | −0.049193 | −0.083297 |
| LOSQ | 129 | 100 | −0.190968 | 28.155772 | −0.119799 | −0.329373 |

Primary increment: `LOS−LO = −0.0317268` OOS R². Paired squared-error improvement (positive would
favour LOS): −21.1184 tick²; t statistics Newey-West −2.0287, stationary bootstrap −2.0330,
non-overlapping ten-second blocks −1.9579.
