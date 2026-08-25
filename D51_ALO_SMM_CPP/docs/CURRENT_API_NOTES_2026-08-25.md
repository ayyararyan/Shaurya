# Current Kotak API notes — 25 Aug 2026

These are dated implementation notes, not a permanent API specification. Re-check the official SDK before later live enablement.

## REST/session

- TOTP login: `https://mis.kotaksecurities.com/login/1.0/tradeApiLogin`
- MPIN validation: `https://mis.kotaksecurities.com/login/1.0/tradeApiValidate`
- MPIN validation returns the dynamic order `baseUrl` plus edit session credentials.
- place: `{baseUrl}/quick/order/rule/ms/place`
- modify: `{baseUrl}/quick/order/vr/modify`
- cancel: `{baseUrl}/quick/order/cancel`
- the current official SDK's post-login order calls use `Authorization=<consumer key>`, `Sid=<edit sid>`, `Auth=<edit token>`, with `application/x-www-form-urlencoded` bodies;
- D51 uses only regular `DAY` LIMIT orders and order source `NEOTRADEAPI`.

The dormant C++ order router matches those current SDK field names (`am,dq,es,mp,pc,pr,pt,qt,rt,tp,ts,tt,ig,os` for place; `vd` for modify validity; `on` for cancel). It is compiled out by default.

## SFeed

Fallback endpoint: `wss://sfeed.kotaksecurities.com/apifeed`. The engine prefers a feed URL returned by the authenticated session when available.

Authentication requests `native_batch`; full depth uses `subscribeFullDepth` with `nse_fo|TOKEN` inputs. The decoder implements the little-endian market-picture message code 7208 and five visible buy/sell levels, with exchange-specific price dividers read from authentication metadata when supplied.

## Order/position stream

For later live work, the package contains the separate `wss://<baseUrl>/realtime` order-update path and parses the fields required for incremental-fill accounting, including order number/status, average price, filled/remaining quantity, side, symbol and token. This parser is unit-tested synthetically but still requires a real-account capture/contract test before live capital.

## Operational assumptions

- Kotak currently requires a whitelisted static IPv4 for order execution; session/order traffic should originate from that address.
- The API currently advertises a 10 orders/second limit; D51 defaults to an internal cap of 8.
- Kotak currently advertises sub-50-ms API execution; D51 does not treat that as an exchange-fill SLA and is designed around ~0.5–2 s information horizons.
- Kotak's current support material states API brokerage is ₹0 per order on Trade Free plans; exchange/statutory charges remain.
- The current official SDK's `logout()` is local token cleanup; close WebSockets and terminate the process/session cleanly at the end of the study day.

Before any live pilot, compare these assumptions with the then-current official SDK and run a one-lot broker/contract-note test outside the strategy.
