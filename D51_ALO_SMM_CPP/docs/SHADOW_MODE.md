# Shadow mode

Shadow mode authenticates and consumes live market data but **never submits an order**. The normal binary is built with the live compile gate OFF, so even `mode=live` cannot place an order.

## Per-second sequence

1. Drain SFeed books into the single-writer strategy state.
2. Mature the previous counterfactual horizon.
3. Label every candidate offset as fill/no-fill and compute hedged markout.
4. Update all online action models and calibration.
5. Apply only the previously selected shadow fill(s) to simulated token-level inventory.
6. Refit the fresh leave-target-strike-out surface.
7. Select the paired front-expiry ATM CE/PE (or keep the strike pinned while inventory exists).
8. Score BUY/SELL/OFF/HOLD actions.
9. Record decisions, health and compact research samples.

## Conservative fill definition

A passive BUY is labelled filled only when the observed ask crosses the hypothetical bid, or when a **new trade after placement** is observed at/below the bid. A passive SELL uses the symmetric bid/new-trade rule. LTP is ignored unless cumulative option volume increased after placement, so a stale historical print cannot manufacture a fill. Exact queue position is deliberately not invented.

## Cold start

With insufficient evidence the policy normally outputs OFF/HOLD. It still learns because every mature state generates counterfactual labels for all configured offsets. Do not lower the EV threshold merely to manufacture activity in the first few days.

## Inventory across days and crashes

The shadow study is **session-based**: simulated inventory begins at zero when a new process starts. The service intentionally has `Restart=no`; a process crash therefore marks that day incomplete rather than silently resetting inventory and contaminating the same day's path. SFeed itself has an internal reconnect loop for ordinary feed disconnects.

If you intentionally restart during the session, treat the restart as a new shadow segment when analyzing the month. The model state persists across completed days; simulated inventory does not represent overnight holdings. End-of-day inventory treatment is evaluated analytically from the retained path rather than carried into the next morning.

## Clean shutdown

SIGTERM/SIGINT saves the persistent model state, writes the daily model snapshot and summary, flushes statistics and exits. Let systemd stop the process normally rather than using SIGKILL.

## Daily checks

Confirm `health.csv` has no sustained feed gaps/drops, surface success is nontrivial, `day_summary.json` contains matured actions, the current instrument file is correct, and `model_state_eod.dat` exists after shutdown. A crash/incomplete day should be noted rather than hidden by automatic restart.
