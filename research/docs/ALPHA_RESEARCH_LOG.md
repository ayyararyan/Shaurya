# Alpha research log

This is the durable, decision-oriented record for exploratory NIFTY alpha work.
It records the exact data, target, execution assumption, and disposition so a
promising-looking diagnostic is not later mistaken for a tradeable result.

## Data discipline

- The active research sample is the completed August 2026 data already on the
  Office Mac. Do not silently fall back to January/February data.
- Keep dates chronological: discovery before validation before final evaluation.
- Never use an incomplete or still-live session as an outcome dataset.
- A midpoint-price result is predictive evidence only. Promotion requires
  executable bid/ask accounting, then fees/slippage and an out-of-sample test.

## 2026-09-02 — Far-expiry put-call-parity lead

**Status: rejected as a directional taker strategy; retained only as an
exploratory state feature.**

### Data and split

- State panels: `surface-states-2026-08-21.npz` (discovery),
  `surface-states-2026-08-26.npz` (validation), and
  `surface-states-2026-08-27.npz` (final).
- All panels are five-second snapshots. Futures bid/ask was reconstructed from
  the recorded futures log midpoint and relative spread.

### Estimand and predictor

- Estimand: signed NIFTY futures log-midpoint return over the next 30 seconds.
- Predictor: the 60-second change in
  `surface__parity_residual_rms_to_forward__far` — the RMS mismatch, across
  far-expiry call/put strikes, between observed put-call parity and the
  futures-implied forward.
- Forecast: causal Ridge model with basic futures state (recent returns,
  spread, microprice dislocation, depth imbalance, short volatility and time
  of day), augmented by that parity predictor.
- The Aug-26-selected 95th-percentile absolute-prediction threshold was frozen
  at `5.887791725829495e-05`; signals are non-overlapping 30-second holds.

### Predictive result (not execution)

The parity predictor had positive rank correlation with next signed futures
return on all three sessions: about +0.25 (Aug 21), +0.20 (Aug 26), and +0.28
(Aug 27) at 30 seconds. It did **not** have stable association with absolute
future return, realised future volatility, or change in the far-minus-near
ATM implied-volatility slope. This is an association, not a causal claim; an
asynchronous quote-update artefact remains plausible.

### Executable result

Result file on the Office Mac:
`/Users/maheit/Documents/Shaurya-research/2026-09-02-parity-executable-21-26-27.json`.

| Session | Trades | Midpoint diagnostic | Bid/ask, no delay | Bid/ask, 5-second delay |
| --- | ---: | ---: | ---: | ---: |
| Aug 26 validation | 61 | +0.76 bps/trade | -0.91 bps/trade | -1.45 bps/trade |
| Aug 27 final | 142 | +0.93 bps/trade | -1.41 bps/trade | -2.08 bps/trade |

The bid/ask numbers include the recorded spread but exclude fees and further
slippage. Therefore the result fails even the most favourable executable test
and must not be retuned on these same days.

### Consequence

Do not cross the spread using this signal. It may later be evaluated as one
input to a broader model or a passive/maker study, but neither has trade or
deployment authority from this result.

## 2026-09-02 — Five-year 500-point short-volatility butterfly request

**Status: blocked for an exact backtest by the supplied archive schema; do not
substitute a rolling-series proxy without calling it synthetic.**

### Requested strategy

The intended position is a weekly 500-point-wide short iron butterfly: sell
the entry ATM call and put, buy the call 500 points above and the put 500
points below, then compare fixed hold-to-expiry with daily/dynamic risk
management based on an entry-time volatility forecast.

### Archive preflight

The requested five-year source is:
`/Volumes/Aryan/NSE/NIFTY_OPTIONS_1MIN_OHLCV_2021-2026.zip`, covering
2021-01-01 through 2026-05-14. It has one-minute OHLCV only, and files are
named `WEEK1` plus `ATM±N`. The archive README states that these are *rolling
ATM-relative series*, rather than fixed-contract continuous series. It has no
contract identifier, exact strike, expiry, implied volatility, bid/ask, or
option-chain snapshot fields.

### Why an exact result is impossible from this source

Holding an entry ATM leg to expiry requires preserving its original strike and
expiry. In this archive, `ATM` and `ATM±10` may change the underlying contract
as spot moves or the nearest weekly contract rolls. Consequently, treating
`ATM±10` as a 500-point wing and marking it until expiry would invent leg rolls
and cannot measure real butterfly P&L. IV-versus-realised-volatility selection
also cannot be reconstructed defensibly without the entry contract's strike,
time to expiry and executable quote.

### Required data to run the requested comparison

At every entry and daily/dynamic rebalance point: contract symbol or ID, strike,
expiry, CE/PE, bid/ask or reliable executable prices, and the NIFTY future or
spot. With that, run fixed contracts through expiry and pre-register daily or
forecast-triggered exits/rolls. The August state tapes can support a short
intraday exercise but cannot supply five years of fixed weekly contracts.

### Correction and reconstructed close-price pilot

The earlier "blocked" conclusion above was too strong. A fixed strike can be
reconstructed from the rolling labels by mapping the entry ATM to the 50-point
strike grid and changing the `ATM±N` lookup as spot moves, while retaining the
original strike and inferred weekly expiry. This remains a close-price proxy,
not an executable bid/ask backtest.

The first hold-to-expiry reconstruction produced 257 clean Monday-to-expiry
500-point iron butterflies. All weeks averaged -0.25 NIFTY points. Requiring
entry ATM IV to exceed trailing-20-session realised volatility selected 213
weeks, averaging +0.27 points with a 53.5% win rate before costs: economically
zero.

A second causal audit forecast the butterfly's actual capped expiry payoff,
`min(abs(settlement - strike), 500)`, from past weeks only. The 52-week expected
payoff filter was +20.28 points/trade in 2024 validation but -16.12 in the
2025--May-2026 final period; partial 2026 was -58.84. At a two-point cost reserve
the final result was -18.12. The IV filter was also effectively zero in the
2025--2026 final period before costs and -77.97 in partial 2026. No entry filter
is promoted. The remaining legitimate experiment is a frozen daily/dynamic
exit or recentering rule, evaluated chronologically rather than fitted to the
full sample.

### Daily management comparison

The frozen comparison marked the original fixed butterfly daily using a flat
ATM-IV Black model, scaled to its observed entry credit. This model mark is
necessary when a fixed 500-point wing leaves the archive's `ATM±10` window; it
is not an observed executable quote. The dynamic exit closes when current ATM
IV no longer exceeds the trailing realised-volatility forecast. Daily
recentring closes the old structure and opens a new ATM ±500 structure only
while that volatility condition remains true.

Gross means over 257 reconstructed weeks were -0.25 points for expiry hold,
+6.45 for forecast exit, and +20.78 for daily recentering. In the untouched
2025--May-2026 period, they were +1.72, +6.83 and +30.94 respectively. Daily
recentring remained +25.99/+18.55/+6.17 points at assumed 2/5/10-point costs
per entry or roll. But partial 2026 remained negative: -24.42 points even at
the two-point ladder, versus -47.64 for hold. Therefore daily recentering is a
research lead, not a promoted alpha: it improves the loss profile and survives
coarse cost stress over combined 2025--2026, but depends on model-imputed marks
and does not survive the latest subperiod.

Office Mac artifacts:
`/Users/maheit/Documents/Shaurya-research/2026-09-02-butterfly-dynamic.json`
and the corresponding `.csv` trade ledger.

## 2026-09-02 — NSGVC v1.0.0 package audit

**Status: historically reproduced; statistically inconclusive and not
execution-confirmed.**

The coworker package
`NSGVC_Reproducible_Research_Package_v1.0.0_2026-09-02.zip` has SHA-256
`5ba9f58cd21a335c95cd8f7582e8e73f616becd222d50603cf6792b6f5e1cc54`.
All 263 package-manifest entries passed size and SHA-256 verification. A clean
Python 3.12 environment on the Office Mac reproduced the frozen model, RR400
cutoff and all 56 entry keys. Maximum prediction-ratio difference was
`6.81e-13`. The NIFTY index ZIP hash matches the package receipt; the available
combined option ZIP cannot be byte-compared directly with the package's six
separate yearly ZIP hashes.

At the six-option-point structure cost, the fixed-500 ledger produces +21.85
points/trade and Rs 79,524 total under the reference 65-unit lot. The stated
approximately Rs 77,870 result is also correct for the capital-aware mix that
falls back to 400-point wings when the 500-point defined loss breaches Rs
20,000: 56 trades, Rs 77,869.97 total, Rs 1,390.54 mean, 58.93% wins, Rs
13,858.35 mean defined risk and Rs 18,973.50 maximum admitted risk.

Independent inference on the fixed-500 cost-6 ledger gives a one-sided t-test
`p=0.1465` and an iid 100,000-resample bootstrap 95% interval for mean points of
`[-18.08, +61.60]`. Development, 2025 validation and researcher-exposed 2026
intervals all include zero. Threshold and structure selection examined several
q cutoffs, RR400 quantiles and wing widths, and 2026 was seen during exploratory
work. Therefore reproduction upgrades the claim from unaudited to reproducible
historical evidence, but does not establish statistical or executable alpha.

## 2026-09-02 — NSGVC independent rebuild from consolidated raw ZIPs

**Status: exact raw-data reproduction over the frozen research window; a new
training-window sensitivity materially weakens confidence in robustness.**

The complete iron-fly and smile pipeline was rerun on the Office Mac from
`NIFTY_1MIN_OHLC_2021-2026.zip` and the independently available consolidated
`NIFTY_OPTIONS_1MIN_OHLCV_2021-2026.zip`. The adapter preserves the package's
declared option/training start of 2023-01-23, its 09:20 option-open convention,
15:29 expiry spot proxy, Black-76 inversions, model splits, q gate and RR400
calibration rule.

The rebuild produced 815 daily smile rows and 6,511 defined-risk structure
rows. Both sets have zero missing or extra keyed rows against the package.
Market quantities and trade economics agree to floating-point precision:
maximum absolute differences are about `1.22e-14` for ATM IV, `9.86e-13` for
RR400, `1.28e-14` for prediction ratio and `1.14e-13` option points for max
loss. The frozen refit again has 726 observations, intercept
`-1.4844407354182474`, coefficients `[0.8215772820234082,
0.08981823810775358]`, and RR400 cutoff `0.0270810062478522`.

All 56 final fixed-500 trade keys match with zero additions or omissions. At a
six-point cost the independently rebuilt ledger has +21.847314 option points
per trade, 58.93% wins and Rs 79,524.224 at the normalized 65-unit lot. This is
an exact raw reconstruction of the package's fixed-500 historical result.

Important sensitivity: the consolidated ZIP also contains 15 valid sessions
from 2023-01-02 through 2023-01-20 that are absent from the coworker's separate
2023 archive and outside the frozen configuration. Including only those extra
old observations—not tuning any gate—changes the 2023-25 fit from 726 to 741
rows, moves the RR400 cutoff from 2.7081 to 2.6121 vol points, selects 63 trades
with only 49 of the original 56 keys, and reduces the fixed-500 cost-6 total to
Rs 32,418.672 with 53.97% wins. The published result is therefore reproducible
for its declared sample, but materially sensitive to the seemingly innocuous
choice of training-window start. Treat that as a robustness warning, alongside
the already inconclusive confidence interval and lack of executable quotes.

Committed audit artifacts live under
`research/nsgvc_raw_rebuild_2026-09-02/`; large reconstructed intermediate
panels remain on the Office Mac under
`/Users/maheit/Documents/Shaurya-research/NSGVC-raw-rebuild-2026-09-02/`.

## 2026-09-02 — NSGVC prospective shadow freeze

**Status: frozen and verified; awaiting the first valid post-freeze option
session.**

NSGVC v1.0 is frozen for prospective evaluation starting 2026-09-03. The
invalid 2026-09-02 capture is explicitly excluded. The model coefficients,
q threshold, RR400 threshold, 09:20 snapshot, first-signal-per-expiry rule,
500/400 risk hierarchy, hold-to-expiry exit and six-point research cost cannot
be changed in response to prospective outcomes. Any revision must receive a
new version and a new future evaluation start date.

The standalone scorer was verified on the 89 archived 2026 rows: its maximum
absolute difference from the package's frozen prediction ratios is
`3.99e-13`. The current historical option panel ends 2026-05-14, so the initial
post-freeze baseline correctly reports zero eligible rows and zero signals with
status `awaiting_post_freeze_data`. This is not a failed trade result; no valid
prospective observation exists yet.

The hash-locked configuration, scoring code, protocol and baseline are stored
under `research/nsgvc_prospective_2026-09-02/`.

## 2026-09-02 — NSGVC historical stability matrix

**Status: encouraging recurring effect, but still statistically inconclusive
and unsuitable for an alpha claim.**

The Office Mac evaluated eight fixed training starts, seven expanding-origin
quarterly blocks, and strict expiry-by-expiry expanding and rolling-252-session
walk-forward variants. All tests retained the IV-only model family, q <= 0.70,
RR400 60th-percentile calibration rule, 500-point width, first qualifying date
per expiry and six-point cost. Walk-forward training admitted only labels from
already-matured prior expiries.

Six of eight starts were positive in 2025 and all eight were positive in the
partial-2026 block, but alternative starts generally reduced partial-2026 mean
P&L from +32.16 to +11.19 points. Quarterly expanding evaluation had three
positive blocks, three negative blocks and one no-trade block; its 37 trades
averaged +16.42 points with p=0.283 and bootstrap interval `[-39.00,+71.01]`.

Strict expanding-history expiry walk-forward generated 47 trades averaging
+15.82 points, but lost 28.63 points/trade in 2024; aggregate p=0.250 and the
bootstrap interval was `[-29.50,+60.93]`. Rolling-252 expiry walk-forward was
stronger: 52 trades, +26.60 points/trade after six points, 57.69% wins,
positive annual means in 2024, 2025 and partial 2026, and +22.60 points/trade
even at ten-point cost. Its p-value was still 0.101 and bootstrap interval
`[-13.53,+66.36]`, so zero remains plausible. Because the rolling-252 variant
was chosen after inspecting these histories, it is exploratory and does not
replace the already-frozen prospective rule.

Artifacts are under `research/nsgvc_historical_stability_2026-09-02/`.

## 2026-09-02 — Rolling-252 NSGVC falsification audit

**Status: six of seven stress criteria passed, but uncertainty and
concentration prevent promotion.**

Raw option minutes were used to reconstruct delayed execution. At a ten-point
deduction, 09:20-close and 09:21-open entries still averaged +22.93 and +22.65
points across the same 52 expiry trades; even 20 points of cost left means near
+12.7. Annual means were positive in 2024, 2025 and partial 2026. The 09:20-open
reconstruction matched the audited ledger within `2.84e-14` points.

Across 125 nearby lookback/q/RR cells, 115 had at least 20 trades: 65.22% were
positive, the median cell averaged +10.86 points and the primary cell ranked at
the 87.83rd percentile. Cell means ranged from -16.42 to +51.97, so the surface
is favorable more often than not but far from uniformly stable.

Gate attribution supports an interaction: ungated entries averaged -16.15,
RR-only -16.74, q-only +7.60 and both gates +26.60 points after six-point cost.
However, removing the five best trades reduced the primary mean from +26.60 to
+2.90 points. The primary one-sided p-value remains 0.101; iid and four-expiry
block-bootstrap intervals were `[-13.53,+66.36]` and `[-9.87,+62.56]`.

The sequential Rs 1 lakh risk simulation used 51 500-point structures and one
400-point fallback, ending at Rs 189,729.25 with a 30.51% maximum drawdown.
Because the block-bootstrap lower bound did not exceed zero, the strict overall
falsification gate failed. Rolling-252 remains an exploratory candidate and
does not replace the existing prospective freeze. Artifacts are under
`research/nsgvc_rolling252_falsification_2026-09-02/`.
