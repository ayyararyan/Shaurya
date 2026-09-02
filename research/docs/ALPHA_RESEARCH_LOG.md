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
