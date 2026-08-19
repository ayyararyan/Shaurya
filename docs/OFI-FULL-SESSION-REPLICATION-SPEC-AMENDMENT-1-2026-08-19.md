# Amendment 1 — publication-boundary acceptance

**Parent protocol:** `R-OFI-FULLSESSION-2026-08-20`

**Parent registration commit:** `af9bec17694b5cf45f1d670113f14b02efb1e418`

**Status:** pre-capture amendment; zero 2026-08-20 rows exist

**Scope:** coverage acceptance only

## Correction

The parent protocol correctly allows a two-second publication tolerance, but §4 phrases the
closing test as requiring a publication at or after 15:40. A snapshot feed can stop publishing
when the regular session ends even though the collector remains connected through the boundary.
Requiring an artificial post-close packet would make acceptance depend on whether Dhan emits a
terminal duplicate, not on whether the regular session was covered.

The binding test is therefore:

- the controller starts before 09:15 and remains alive through 15:40 plus its declared buffer;
- every required channel has a first retained row no later than 09:15:02;
- every required channel has a last retained row no earlier than 15:39:58;
- depth20 and depth200 apply the same bounds to complete-book states;
- analysis remains clipped exactly to `[09:15:00, 15:40:00]` IST.

The tolerance is symmetric around the close only for coverage acceptance. It does not admit
post-close rows into any predictor, response or support calculation.

## Unchanged

Instrument, channels, session clock, fixed leads, complete grids, causal gap, split, embargo,
claim boundary, SIG-21 ineligibility, output contracts and order prohibition are unchanged.
