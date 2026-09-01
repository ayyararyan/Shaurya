# Delta-hedged volatility carry — 2026-09-01

## Verdict

**Reject the tested intraday volatility-carry strategy.** The historical realized-volatility
forecast remains useful as a forecast, but comparing it with executable ATM-straddle IV does not
produce positive delta-hedged P&L in the January-February fixed-contract archive.

## Protocol

- Fit the existing index-only histogram realized-volatility model using accepted observations
  strictly before 2026-01-01.
- Forecast 30- and 60-minute realized volatility at five-minute decision points.
- Use one fixed nearest-expiry NIFTY call/put pair per session, chosen near the first valid futures
  quote. The strike and contracts do not roll during a trade.
- Infer executable straddle bid/ask IV with Black-76 and compare forecast volatility with bid/ask
  IV, using fixed edges of 0, 2, and 4 volatility points.
- Enter one second after the decision. Cross recorded option bid/ask at entry and exit.
- Delta hedge with the recorded NIFTY-futures bid/ask every 1, 5, or 15 minutes and close the hedge
  at exit.
- Select among the 18 fixed horizon/edge/hedge-cadence candidates on January only. Apply the selected
  rule unchanged to February.
- Report a 0/0.5/1/2 option-point reserve beyond the observed spreads already paid by the simulator.

## January selection

All 18 candidates were negative before the extra reserve. Slower hedging reduced the loss but did
not reveal positive carry.

Selected as the least-negative rule:

- Horizon: 30 minutes.
- Forecast-versus-IV edge: 4 volatility points.
- Hedge cadence: 15 minutes.
- Trades: 58 across 10 active sessions.
- Long/short trades: 9/49.
- Gross: -51.69 points total, -0.89 points per trade.
- After a one-point reserve: -109.69 points total, -1.89 points per trade.
- Positive days after reserve: 2/10.

## February unchanged evaluation

- Trades: 72 across 14 active sessions.
- Long/short trades: 2/70.
- Gross: -17.09 points total, -0.24 points per trade.
- Gross win rate: 48.6%.
- After a 0.5-point reserve: -53.09 points total, -0.74 points per trade.
- After a one-point reserve: -89.09 points total, -1.24 points per trade.
- Positive days after a one-point reserve: 5/14.
- Session-level one-sided Wilcoxon p-value after a one-point reserve: 0.914.

The first one-minute-hedge pass was also negative. Its February option-versus-hedge decomposition
was internally consistent: 70 short trades earned +10.4 option points but lost -32.6 points through
the hedge path; two long trades earned +14.0 points net. Testing slower fixed hedge schedules did
not rescue the economics.

## Decision

Do not promote, tune on February, or mine August for a rescue. The January discovery gate failed
for every predeclared configuration, and February independently remained negative. The durable
realized-volatility model should remain a forecasting/risk input rather than a direct intraday
straddle-carry strategy under this execution design.

Machine artifacts:

- `/Users/maheit/Documents/Shaurya-research/2026-09-01-delta-hedged-volatility-carry`
- `/Users/maheit/Documents/Shaurya-research/2026-09-01-delta-hedged-volatility-carry-cadence`
