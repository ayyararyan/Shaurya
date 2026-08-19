# SIG-21 calibration runbook

**Protocol:** `H-SIG21` · **Role:** calibration only · **Outcome join:** forbidden

## Scientific boundary

- **Signal/treatment source:** Dhan depth200 for one NIFTY front-month future. Every candidate,
  magnitude, baseline score and episode must originate from this channel.
- **Measurement support:** depth20 for the same future. It supplies the later BBO midpoint and the
  near-book spread/depth/OFI controls only. It can never create or backfill an anomaly.
- **Grid:** the pushed registration already fixes
  `8 atomic types x 2 sides x 2 distance bands x 2 thresholds x 2 Z gaps x 3 horizons = 384`
  cells. Calibration measures support and power; it does not select axes or inspect cell outcomes.
- **Sample:** five full post-registration sessions, followed by a pushed numeric power artifact.
  Only then may adequately powered cells enter a separate 20-session evaluation sample.

## Before each session

1. Resolve the current NIFTY front-month future from the same-day Dhan master and verify the exact
   security ID to trading-symbol mapping. Never carry an ID across trading days without checking.
2. Start before 09:15 IST and request enough duration to cover the entire 09:15–15:30 session.
3. Use the `--sig21-calibration` profile together with `--enable-depth200`. The profile rejects a
   missing depth200 source, disabled depth20 support, or a requested duration below 22,500 seconds.
4. Use a new output root/run ID. Do not append to DAT-20 or another session's tape.
5. This path is read-only market-data capture. It does not authorise or touch live orders.

Illustrative invocation; resolve the paths, symbol and security ID from the same-day environment:

```bash
.venv/bin/python -m shaurya.cli.capture_dhan \
  --credentials /path/to/read-only-dhan.env \
  --security-master /path/to/same-day-master.csv \
  --security-id SECURITY_ID \
  --expected-symbol EXACT_TRADING_SYMBOL \
  --enable-depth200 \
  --sig21-calibration \
  --duration-seconds 22620 \
  --output-root artifacts/sig21-calibration
```

The resulting capture metrics record under `test_configuration.sig21_protocol`:

- `protocol_id = H-SIG21`;
- `sample_role = calibration_only`;
- `signal_source_channel = depth200`;
- `response_control_channel = depth20`;
- `registered_family_size = 384`;
- the registration commit; and
- `outcome_join_allowed = false`.

## Session acceptance

A session counts toward the five only if all of the following hold:

- the tape covers the complete regular session rather than merely requesting a long duration;
- depth200 and depth20 both produced recurring packets for the same verified future;
- depth200 contains valid two-sided 200-level states rather than startup packets only;
- reconnect, gap, partial-book and crossed-book intervals remain explicitly flagged and excluded;
- the run completes with a manifest, metrics, quality audit and non-empty append-only tape; and
- no SIG-21 event is joined to a future midpoint and no response statistic is inspected.

A failed or partial session is preserved and marked ineligible; it is never merged into a later
session to manufacture a full day.

## After each accepted calibration session

- Record run ID, contract, date, tape checksum, packet/channel counts, quality exclusions and
  full-session acceptance in `TASKS.md` or a linked dated evidence artifact.
- Buffer current-session candidate magnitudes. They may update the unusualness baseline only for
  later sessions, never their own thresholds.
- Do not run the response-label builder, matched-control outcome join or Romano-Wolf inference.

After session five, compute the complete pre-outcome power artifact from unconditional calibration
quantities, push it, verify the remote hash, and defer every cell that fails the registered MDE or
support gate before opening evaluation outcomes.
