# DAT-01 — Dhan client reconciliation

## Decision

`Mushin_Gamma/src/mushin_gamma/dhan_io.py` is the structural base for Shaurya's canonical
Dhan client. It was the more complete implementation for identity resolution and production
credential/context handling: typed contracts, cached expiry discovery, ATM option resolution,
and defensive unwrapping of the two response-envelope shapes seen in Dhan.

The canonical implementation is **market-data-only**. It lives at
`shaurya.data.dhan_client.DhanClient`; all credential values are redacted by representation,
the credential file is an explicit handle outside the repository, and failures contain only
sanitized error types/codes.

## What was retained from the losing Shoshin client

Shoshin's useful differences were merged rather than discarded:

- bounded retry with exponential backoff and Dhan `DH-429` detection;
- request pacing;
- nested rolling-option response normalization;
- UTC epoch to timezone-aware IST normalization for historical frames;
- intraday, daily, expired-option, and option-chain data methods behind one adapter.

## What was dropped from Shoshin, and why

- Its global dependency on `src.config.config` and `DhanAPIError` was strategy-specific and
  violates Shaurya's one-way dependency rule.
- `verify_expiry_code()` returned `1` without verifying anything; the name made a hard-coded
  assumption look like evidence.
- `place_order()` ignored its `option_type` and `strike` arguments and sent the NIFTY
  underlying security ID. `cancel_all_nifty_orders()` compared option orders to that same
  underlying ID. Both are unsafe as option-execution implementations.
- All order placement/cancellation was removed regardless of implementation quality because
  binding decision D7 authorizes Dhan for data and Kotak alone for execution.
- Hard-coded NIFTY/5-minute choices became explicit method arguments so the module remains
  strategy-agnostic.

## What was dropped from the Mushin base, and why

- `DhanOrderClient`, correlation IDs, price rounding, cancellation, order status, and trade
  fills were removed under D7's Kotak-only execution boundary.
- Recursive searches through neighbouring strategies' `.env` files and best-effort scraping
  of RTF/text token files were removed. They made credential provenance ambiguous and could
  select an unintended account. Shaurya accepts one explicit, permission-checked credential
  handle.
- Project-root and strategy-layout assumptions were removed.

## Feed harvest decision

Mushin's `DhanFeed` supplied the useful callback/subscription shape and Still_Water supplied
the useful health/introspection pattern, but neither met DAT-02: neither provided full
reconnection ownership, an application heartbeat, source-gap semantics, 20-level side-packet
parsing, or durable tape output. Shaurya therefore generalizes their patterns in
`shaurya.data.dhan_stream` rather than copying either feed class.

The installed DhanHQ 2.2.0 `FullDepth.connect()` also prints the authenticated WebSocket URL.
Shaurya does not call that helper; it implements the documented binary protocol directly so
the token never enters stdout/logs.
