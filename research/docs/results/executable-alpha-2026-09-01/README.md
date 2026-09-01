# Executable surface and sub-minute lead results — 2026-09-01

## Decision

No strategy is promoted. Two statistically interesting forecast effects fail executable economics.

## 1. Butterfly VolArb audit

The July robustness artifacts were already complete. The original February no-delay result was
1,701 trades and +₹77,505 net. A one-second entry delay changed gross P&L to -₹109,519 and net P&L
to -₹220,404. Fill-bar revalidation reduced the loss but remained -₹27,842 net. A signal defined
directly in executable-edge space produced one trade and lost ₹110. The crossing strategy is
rejected as same-bar quote flicker rather than persistent executable mispricing.

## 2. ATM-IV and near/far calendar spreads

Twelve fixed candidates tested near-ATM IV mean reversion and near/far IV-spread mean reversion at
30, 60, and 300-second holds. Signals were fit on August 19, validated on August 21, and diagnosed
unchanged on August 26 and 27. Entry was delayed one five-second observation, the ATM strike had to
remain fixed through exit, and observed straddle bid/ask prices were used.

No candidate survived validation. The least-negative validation candidate was 300-second near-IV
mean reversion at -1.04 option points per trade after the one-point reserve. The same rule averaged
-1.63 points on August 26 and -0.89 points on August 27. Most candidates were negative even before
the extra cost reserve, so PCA/JEPA escalation did not pass the economic gate.

Machine artifacts:

`/Users/maheit/Documents/Shaurya-research/2026-09-01-executable-surface-alpha`

## 3. Options-leading-futures hypothesis

A fixed nearest-expiry ATM call/put pair was selected causally in each of 39 January-February
sessions. The option-implied forward was `strike + call_mid - put_mid`. Trailing returns over
1/2/5/10/30 seconds were tested against strictly future NIFTY-futures returns over the same horizon
set with zero-, one-, and two-second embargoes. Inference used the 39 sessions as independent units,
with reverse futures-to-options and futures-autocorrelation controls.

The lead is real as a quote-prediction fact. With a one-second embargo, all 25 horizon pairs passed
Holm correction. The strongest region was a 5-10-second option move predicting the next 5-10
seconds of futures movement, with median daily Spearman correlation around 0.12-0.13 and the same
positive sign in all 39 sessions. The reverse futures-to-options effect was near zero.

It is not an executable crossing alpha. A fixed 10-second option signal, one-second entry delay,
and five-second futures hold was selected using January only. The best of eight limited threshold
variants was the 90th-percentile option residual:

- January: 18,873 trades, -1.04 bps per trade gross.
- February unchanged: 18,723 trades, -1.10 bps per trade gross.
- February positive sessions: 0 of 19.
- Adding fees worsens the result; the quoted gross figures already cross futures bid/ask twice.

The January-selected signal was also applied unchanged to the August 19/21/26/27 surface-state
tapes. Because those panels are sampled every five seconds, this is a more conservative five-second
entry delay followed by a five-second hold. It generated 737 trades and lost -2.17 bps per trade
gross. Every August session was negative. This is independent recent confirmation that the quoted
lead cannot be crossed profitably.

Machine artifacts:

- `/Users/maheit/Documents/Shaurya-research/2026-09-01-subminute-option-futures-lead`
- `/Users/maheit/Documents/Shaurya-research/2026-09-01-executable-option-futures-lead`
- `august-replication.json` inside the executable option-lead artifact directory

## Conclusion

The remaining economic interpretation is market-data latency and price discovery: option-implied
quotes update ahead of the futures quote, but not by enough to pay the crossing spread. This feature
may still help passive order placement, execution timing, or adverse-selection avoidance. It should
not be represented as profitable directional alpha.

## 4. Conservative passive-maker test

The frozen January option-residual signal was tested as a futures limit-order strategy. Orders were
posted one second after the signal at the current bid for a predicted rise or current ask for a
predicted fall. A fill counted only when the opposite quote moved strictly through the limit; a
simple touch did not count. Exits crossed the spread. January selected only order lifetime and hold
time from 12 fixed combinations, using net bps per submitted order after a 0.5-bp per-fill reserve.

The least-negative configuration was a one-second order life and ten-second hold:

- January: 26,610 orders, 306 strict fills (1.15%), -1.21 bps per fill gross, 0/20 positive days.
- February unchanged: 27,943 orders, 319 strict fills (1.14%), -1.04 bps per fill gross,
  0/19 positive days.
- February after a 0.5-bp reserve: -1.54 bps per fill.

The maker branch is rejected. Orders that receive conservative fills are adversely selected; earning
one side of the spread does not rescue the signal. The selected one-second lifetime cannot be
replicated honestly on the five-second August state panels, and the uniformly negative January and
February results do not justify mining the raw August tapes for a rescue.

Machine artifact:

`/Users/maheit/Documents/Shaurya-research/2026-09-01-passive-option-futures-maker`
