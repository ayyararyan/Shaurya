# Far-parity passive-maker audit

The frozen far-expiry parity predictor was evaluated as a passive NIFTY futures entry rather than a spread-crossing taker. Signals retain the previously frozen 30-second horizon and Aug-26-selected prediction threshold. Raw Aug 26 and Aug 27 tapes supplied actual best bid/ask, displayed best-level quantities and cumulative futures volume.

The headline simulation places one 65-unit order at the same-side best quote after 250 ms, requires executions to clear the full displayed queue plus the order, cancels after five seconds, and exits with a marketable order 30 seconds after the original signal. A 0.5 bp completed-trade fee reserve is deducted. Displayed-queue depletion counts executions but not cancellations, so the full-queue model is conservative. An optimistic first-touch model provides the opposite bound.

## Result

On Aug 26, the headline model filled 8 of 61 signals (13.11%) and lost 1.063 bps per fill after the fee reserve. On Aug 27, it filled 25 of 142 (17.61%) and lost 0.056 bps per fill. Pooled across 203 signals, 33 filled, total net P&L was -9.896 bps, and average P&L was -0.049 bps per signal. Its gross break-even fee was only 0.200 bps per fill.

The optimistic touch model filled 93 of 203 signals but also lost: -12.574 bps pooled, or -0.062 bps per signal after the same fee reserve. Its gross break-even fee was 0.365 bps per fill. Across all 18 combinations of zero/250/1000 ms latency, one/five-second TTL and touch/half/full displayed queue, no configuration was profitable at 0.5 bp both by session or when pooled.

The headline opportunity bootstrap interval was `[-0.132,+0.030]` bps per signal with only 11.42% bootstrap probability of a positive mean. The optimistic-touch interval was `[-0.193,+0.067]`, with 17.18% probability of a positive mean.

## Decision

Reject the parity lead as both a taker and passive-maker trading strategy under these data. The midpoint association is real as a diagnostic, but it does not convert to execution profit. Do not tune queue fraction, latency or order lifetime on Aug 26/27 to rescue it. Retain the parity residual only as a possible state/quality feature in a separately trained future model.

The simulator necessarily assigns cumulative-volume increments to the recorded last price because native aggressor-side events are unavailable. It ignores cancellations ahead, making the full-queue case conservative, while the touch case is deliberately optimistic. Both bounds fail after a modest fee reserve.
