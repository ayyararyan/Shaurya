# Kotak Neo setup for D51 ALO-SMM

This records the package's API assumptions as of **25 August 2026**. Re-check Kotak's current documentation before live enablement.

## Account/API assumptions

D51 uses Neo Trade API, regular LIMIT orders only, and an internal order-rate cap below Kotak's current advertised API limit. The distributed build is shadow-only (`ALO_ENABLE_LIVE_ROUTER=OFF`). The source tree contains the real place/modify/cancel router, but neither a config typo nor exported credentials can make the normal build place an order.

API-routed orders on eligible Trade Free plans are modelled with ₹0 brokerage; statutory/exchange charges remain and are configurable under `costs`.

## Authentication

1. TOTP login with consumer key, mobile number, UCC and current TOTP.
2. MPIN validation using the first-stage SID/view token.
3. Read the returned edit SID/token and dynamic order `baseUrl`.
4. Reuse a persistent HTTP/2-capable libcurl handle for later REST calls.

For unattended AWS shadow startup, `KOTAK_TOTP_SECRET` can hold the base32 TOTP seed and the engine generates the RFC 6238 code locally. If you prefer not to store that seed, omit it and manually provide a current `KOTAK_TOTP` when launching. Secrets are never written to JSON, statistics, or month bundles.

## Static IP / AWS

Attach an AWS Elastic IP and whitelist it in Neo before any later order testing. Keep login/session and eventual order traffic on that same public IPv4. Shadow market-data operation can be developed before live enablement, but the production host should still use the final EIP so network measurements are representative.

## Instrument master

Never use the packaged dummy tokens. Download a current Kotak scrip master and generate the front-expiry NIFTY window. The helper can update both the option file and the nearest NIFTY future in the JSON:

```bash
python3 scripts/prepare_instruments.py \
  --master /path/to/current-master.csv \
  --underlying NIFTY \
  --center 24300 \
  --width 7 \
  --out config/instruments.csv \
  --update-config config/alo_smm.json
```

`--center` only chooses a broad strike window; the C++ engine dynamically selects ATM from the live future. Inspect expiry, lot size, tick size, symbols, futures token and the CE/PE pairing before starting the service. Run `scripts/preflight_shadow.sh` after exporting your credentials.

## Market data

The SFeed client uses `native_batch`, subscribes to full depth for the configured future and option window, and decodes message 7208. The feed URL remains configurable because Kotak can change routing.

## Cost configuration

The shipped statutory-cost numbers are research defaults based on the August 2026 study. Reconcile them with actual NSE/Kotak contract-note charges before any live pilot and update the JSON if rules change.
