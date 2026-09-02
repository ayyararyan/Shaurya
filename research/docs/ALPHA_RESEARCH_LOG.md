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
