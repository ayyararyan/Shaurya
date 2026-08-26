# Actual-premium PUT P&L sanity check

The frozen signal sample contains 57 of the 108 expiry-plus-VIX-rise days: buy the ATM weekly PUT at the 09:17 minute close when the initial window is low-before-high. The sequence hit is target low-before-high during 09:18–09:45. Entry and exit use observed option minute-bar closes. The exact 09:17 strike is tracked through exit; this corrects 16 days where the dynamic ATM series rolled to a different strike.

## Observed economics

- Signal N: **57**; sequence hits: **33**; misses: **24**; hit rate: **57.9%**.
- Entry PUT premium: mean **62.96**, median **56.85** points.
- Entry spot to target low, all signal days: mean **33.0** points (0.15%), median **28.3** points (0.14%). Positive means spot fell below entry.
- PUT at target-low minute, all days: mean **79.60**, median **72.00**. P&L: mean **+16.64** points / **28.1%**, median **+10.55** / **16.3%**.
- Hit-day exit at target low: average gain **8.33 points / 12.5%**; median **2.30 / 6.0%**.
- Miss convention: conservatively exit when spot first reaches the target-window high, which occurs before its low on these days. Adverse spot excursion: mean **8.9 points / 0.04%**, median **10.0 / 0.04%**. Exit PUT premium: mean **55.30**, median **52.05**; P&L mean **-5.40 / -8.7%**, median **-5.93 / -10.1%**.
- Sequencing and premium profitability are not identical: only **24/33** sequence-hit exits made money, while **8/24** sequence-miss stop exits still had positive premium P&L.

## Breakeven and stop math

Using mean premium returns, average win is **12.5%** and average loss is **8.7%**. At the observed 57.9% hit rate: 0.579×12.5% − 0.421×8.7% = **3.6% per trade**. The return-based breakeven hit rate is **41.1%**. In premium points the same calculation is 0.579×8.33 − 0.421×5.40 = **2.55 points per trade**. With only 57 observations, the mean-return t-test is not significant (p=0.237).
At a forced 50% hit rate: 0.5×12.5% − 0.5×8.7% = **1.9% per trade**, or **1.46 premium points**.
The maximum tolerable average loss is **17.2%** at the observed hit rate and **12.5%** at a 50% hit rate. A practical conservative starting stop is therefore about **10.0% of premium paid**, leaving a 20% cushion below the stricter theoretical ceiling.

## Caveats

This is an in-sample, post-selected, 57-trade paper backtest. Minute-bar closes are actual observed traded prices but not guaranteed executable bid/ask fills; spreads, slippage, fees, taxes, and intraminute ordering are not modeled. The extrema-based hit/miss exits are hindsight path proxies, not yet a fully specified live stop or profit-taking rule. Prospective validation is required.
