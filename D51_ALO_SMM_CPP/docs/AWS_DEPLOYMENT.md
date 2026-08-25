# AWS deployment

## Recommended host

Use a normal compute-optimized Linux instance. The measured information horizon is hundreds of milliseconds to seconds; deterministic networking, clock discipline and avoiding noisy/burstable CPU matter more than extreme core count. Start in the Mumbai region and measure RTT/jitter from candidate AZs to Kotak endpoints.

## Static IPv4

Attach an Elastic IP and use that host for the eventual Neo session/order path. Whitelist the EIP in Neo before any later order testing. Avoid NAT or egress paths that change the source address.

## Install

```bash
sudo mkdir -p /opt/d51-alo-smm
# copy/unzip package into /opt/d51-alo-smm
cd /opt/d51-alo-smm
./scripts/bootstrap_ubuntu.sh
./scripts/build_release.sh
sudo mkdir -p /etc/alo-smm
sudo install -m 600 .env.example /etc/alo-smm/alo-smm.env
# edit /etc/alo-smm/alo-smm.env as root
```

Refresh the current Kotak scrip master, run `prepare_instruments.py --update-config ...`, export the environment once, and run `scripts/preflight_shadow.sh` before installing automation.

## systemd

```bash
sudo cp systemd/alo-smm.service /etc/systemd/system/
sudo cp systemd/alo-smm.timer /etc/systemd/system/
sudo systemctl daemon-reload
```

For manual daily control, start/stop `alo-smm.service`. For unattended weekdays, enable the optional timer:

```bash
sudo systemctl enable --now alo-smm.timer
```

The timer launches at **03:40 UTC / 09:10 IST, Mon–Fri**. It does not know NSE holidays. The service has a 6h35m runtime limit so shutdown is graceful after the session. `Restart=no` is deliberate: the feed client reconnects ordinary WebSocket failures internally, while a process crash should mark the shadow day incomplete rather than silently resetting simulated inventory.

The service launches through `scripts/run_shadow.sh`, which records the non-secret binary/config/instrument hashes and run environment before starting the C++ engine.

## Clock / filesystem

Keep `chrony` healthy. Persist `state/` and `stats/` on EBS. Do not rotate model state during the study. Logs may be handled by journald; raw market depth is intentionally not archived.

## Secrets

A root-owned EnvironmentFile is adequate for a private research instance; AWS Systems Manager/Secrets Manager is stronger if preferred. Never place the consumer key, MPIN or TOTP seed in JSON, source control or the month bundle.

## Morning instrument refresh

The engine does not guess derivative tokens. Automation should refresh the Kotak master and regenerate `config/instruments.csv` plus the front future before the timer fires. If you cannot make that reliable, refresh manually; a wrong derivative token is worse than missing a shadow day. `preflight_shadow.sh` will fail on the packaged dummy-token range and a zero futures token.
