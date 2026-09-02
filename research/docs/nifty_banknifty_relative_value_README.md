# NIFTY–BANKNIFTY futures relative-value test

Date: 2026-09-02

## Question

Does a short-horizon, beta-hedged spread between NIFTY and BANKNIFTY futures
mean-revert slowly enough to trade after crossing both futures bid–ask spreads?

## Protocol

- January 2026 (20 sessions): choose from 36 pre-fixed configurations only.
- February 2026 (18 usable sessions): one unchanged out-of-sample evaluation.
- The 19 February session was excluded because it contained no BANKNIFTY futures
  file; no other session was excluded.
- Each signal uses a rolling return beta, lagged by one second, and a lagged
  z-score of the hedged NIFTY/BANKNIFTY return spread.
- On a signal, both legs enter one second later at their actual ask/bid, hold for
  30, 60, or 300 seconds, then both legs exit by crossing their actual quote.
- January grid: beta lookback 300/900 seconds; signal 30/60/300 seconds;
  entry z-score 1.5/2.0; hold 30/60/300 seconds.
- Results are normalized to one NIFTY-leg notional.  The cost ladder adds
  0/0.5/1/2 bps per round-trip spread trade after the observed quotes.

## Result

No candidate was profitable even before added reserve costs.  The least-bad
January candidate was beta lookback 900 seconds, signal 300 seconds, z=2.0,
and 300-second holding period:

| Period | Trades | Gross bps/trade | Positive days |
|---|---:|---:|---:|
| January selection | 650 | -1.17 | 0 / 20 |
| February frozen evaluation | 566 | -1.31 | 0 / 18 |

The February result becomes -1.81, -2.31, and -3.31 bps/trade with 0.5, 1.0,
and 2.0 bps additional cost reserves respectively.  The daily one-sided
Wilcoxon p-value is 1.0: all daily totals have the losing sign.

## Decision

Reject this relative-value mean-reversion family.  It is structurally losing
at executable quotes, not merely insufficiently robust.  Do not mine nearby
thresholds or hold times from the same data.

Machine-readable output and the per-trade February ledger are stored outside
the repository at:

`/Users/maheit/Documents/Shaurya-research/2026-09-02-nifty-banknifty-relative-value/`
