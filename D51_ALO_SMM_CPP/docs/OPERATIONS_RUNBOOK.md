# Operations runbook — one-month shadow study

## Before the month

Use an AWS instance with Elastic IP, build the shadow-only binary, install secrets outside the package, verify `chrony`, verify statutory-cost assumptions, and prepare the current NIFTY derivatives master. Run `scripts/validate_release.sh` once on the target host.

## Every trading morning

1. Refresh the Kotak scrip master and regenerate a front-expiry NIFTY chain with enough paired strikes for the leave-target-strike-out surface.
2. Let `prepare_instruments.py --update-config config/alo_smm.json` update the current future, then manually inspect symbol/expiry/lot/tick information.
3. Export `/etc/alo-smm/alo-smm.env` and run `scripts/preflight_shadow.sh` if starting manually.
4. Confirm JSON remains `mode=shadow` and no live acknowledgement variables are set.
5. Start the service (or let the optional weekday timer start it) and inspect the first minutes of journal output.
6. Confirm `health.csv` grows and surface success becomes nonzero.

## During the day

Do not tune offsets or thresholds because of one good/bad hour. The purpose is to observe a frozen architecture adapting from counterfactual outcomes. Intervene only for operational failures: bad tokens, repeated feed/login errors, time sync, disk pressure or a process crash.

The engine's SFeed client reconnects on ordinary WebSocket errors. The systemd service intentionally does not auto-restart the process; a crash is an incomplete day and should be recorded as such.

## After the session

Allow the runtime limit or a normal `systemctl stop alo-smm` to send SIGTERM. Verify daily summary/action stats, `model_state_eod.dat`, run hashes/provenance, and reasonable disk use. End-of-day shadow inventory is a research outcome; the next process starts simulated inventory from zero.

## Weekly review

Review operations and data integrity, not strategy cherry-picking. Record any code/config change with date/version. If a bug changes features or counterfactual labels, analyze pre/post-fix days as different model versions.

## Month end

```bash
./scripts/month_bundle.sh
```

Bring the resulting ZIP back for walk-forward calibration, stability testing and a live-readiness decision. It excludes credentials and raw market data.
