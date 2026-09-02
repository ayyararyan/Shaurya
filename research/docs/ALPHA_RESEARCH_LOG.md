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

## 2026-09-02 — Far-parity passive-maker audit

**Status: rejected; neither taker nor maker execution converts the midpoint
association into a profitable strategy.**

The frozen 30-second far-parity signal was replayed against raw Aug 26 and Aug
27 NIFTY futures books. The raw reduction retained 16,303 and 27,526 valid
books with actual best prices, displayed quantities and cumulative volume.
The headline maker places one 65-unit order after 250 ms at the same-side best,
requires the full displayed queue plus the order to execute within five
seconds, then crosses the spread to exit at the original 30-second horizon.

The headline filled 8/61 Aug-26 signals and 25/142 Aug-27 signals. After a
0.5 bp fee reserve it lost 1.063 and 0.056 bps per fill respectively. Pooled
P&L was -9.896 bps across 203 opportunities, or -0.049 bps per signal; gross
break-even cost was only 0.200 bps per fill. An optimistic first-touch fill
model also lost -12.574 bps pooled and broke even at only 0.365 bps per fill.

None of the 18 latency/TTL/queue configurations was profitable at 0.5 bp both
by session or pooled. Bootstrap probability of a positive opportunity mean was
11.42% for the headline and 17.18% for optimistic touch. Do not tune the same
days to rescue the result. Artifacts are under
`research/parity_maker_audit_2026-09-02/`.

## 2026-09-02 — Full strategy reuse and delayed-target audit

**Status: three forecast features retained; no profitable strategy claim.**

Every implemented family was inventoried: JEPA, OpenEvolve, paper replications,
formula mining, sparse phase, regime/jump, directional baselines, historical
option predictors, real-tape mining, gap rules, relative value, parity and
delta-hedged volatility carry.

The reusable results are: trailing 30-second futures volatility for 5–30-second
future volatility; trailing 10-second futures volume as an incremental
30-second volatility feature; and the option/surface state block for the
absolute five-minute rolling-ATM straddle move. With a five-second target
embargo, the latter added +12.61 and +6.40 percentage points of MAE skill over
the futures-state baseline on Aug 26 and Aug 27.

ATM call-minus-put movement and L1 futures imbalance are retained only as
execution-state features. Both predict very small midpoint changes, but neither
supports crossing the spread. JEPA velocity and apparent IV/term mean reversion
were downgraded because their headline effects collapsed when the outcome began
five or ten seconds later.

Full definitions, evidence ledger, research mapping and machine output are in
`research/docs/results/strategy-signal-audit-2026-09-02/`.
