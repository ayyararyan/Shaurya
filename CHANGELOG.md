# Shaurya Changelog

Shaurya uses semantic versioning. Each release records the implementation evidence relevant
to strategies that pin the package.

## Unreleased

### DAT-15 — cross-channel alignment-error measurement

- Added a reproducible retained-tape analyzer for causal quote-age distributions, a clearly
  labelled first-post-print-BBO classification-flip proxy, activity/depth/time/age breakdowns,
  and coalesced-interval frequency, excess-size, and attributable-volume coverage.
- Live-ran it across all five pre-existing tapes and three 2026-08-19 captures: 38,572 rows and
  482 prints. Healthy-core quote age was 238.7 ms median / 462.6 ms p95 with 5/320 proxy flips;
  the all-tape result, including a reconnect-heavy cross-tier stress run, was 212.1 ms median /
  3.82 s p95 with 5/429 flips and 42 degraded prints.
- Measured 206/482 coalesced intervals; excess unseen volume was 180 units median, 2,080 p95,
  7,215 max, and last quantities covered 32.0% of increment volume. The stress-run depth-tier
  comparison, n=12 afternoon slice, and absence of midday/options are explicit limitations, not
  generalized away. Five focused regression tests plus the full suite cover the analyzer.

### DAT-14 / CON-01 — causal trade-direction classification at capture

- Live-verified the capture-time classifier on simultaneous Standard+depth20 feeds for NIFTY and
  BANKNIFTY front-month futures over 10 minutes. The 313 positive-volume prints yielded 158 buy,
  154 sell, and 1 unclassified; the real stream exercised 311 quote-rule classifications and the
  first live tick-rule fallback. One print degraded for no prevailing quote, all 313 carried both
  version stamps, and 113 were explicitly coalesced. Scope remains two futures/depth20/one morning
  window; options, depth200 selection, and other times of day are not represented.

- Added the pure, versioned `quote-mid-tick-v1` classifier: prints above/below the prevailing
  midpoint are buys/sells, exact-midpoint prints use the last differing trade price, and absence
  of that price remains explicitly unclassified.
- Added bounded capture-path state and versioned alignment rule
  `latest-complete-depth-before-print-v1`. It selects only a complete 20/200-level BBO already
  received before the print, records both BBO-leg timestamps, the composite timestamp, selected
  channel and conservative quote age, and degrades stale/missing/crossed quotes instead of
  silently forward-filling them.
- Bumped CON-01 tape rows to schema `1.1.0` while retaining read compatibility with existing
  `1.0.0` tapes. Classified rows retain the last price/quantity, cumulative-volume increment,
  exact BBO used, freshness bound, side/reason, classifier and alignment versions, and explicit
  degraded/coalesced flags; a coalesced sign is never assigned to unseen increment volume.
- Earlier dry-run verification on all 21,279 retained rows found 12 positive-volume print intervals
  classified
  (3 buy, 8 sell, 1 unclassified), of which 1 was degraded and 5 were coalesced. Both pytest entry
  points pass 100 tests; strict mypy and Ruff are clean. No live DAT-14 capture was attempted while
  the market was closed. DAT-15 remains separate from this live-verification claim.

### DAT-03, DAT-04, DAT-05, DAT-06, DAT-07, DAT-09, and DAT-11-13 — storage, replay, quality, identity, capacity

- Live-verified DAT-11 on 2026-08-19: the 20-level endpoint accepted every tested one-message
  prefix through 50 instruments and rejected 51, 52, and 53 wholesale. This corrects the
  prior-day 52-working bound, which did not reproduce. The probe now freshly validates both
  bracket endpoints, timestamps every candidate, exposes tested-candidate monotonicity, and
  bounds socket-close latency; the dated acceptance table is retained under `docs/live-evidence/`.
- Added a fresh-socket solo-rate mode and ran NIFTY-Aug2026-FUT alone four times for 15 seconds.
  It delivered 116, 120, 114, and 114 parsed rows versus 116 inside the 50-instrument subscription.
  Removing 49 instruments did not materially raise the row rate,
  ruling out shared socket bandwidth collapse. The preliminary rate-cap interpretation was
  superseded immediately: DAT-16 shows ~4.17 same-timestamp rows per fixed 500 ms snapshot, so the
  solo row-count test is `not-discriminated`, while timestamp cadence identifies a 2 Hz snapshot
  clock and a 500 ms D23 netting bound.
- Live-verified DAT-12 at the reproduced 50+50 load: one socket delivered all 50 instruments
  from message one and none from message two, while a fresh socket delivered all 50 from the
  unchanged second set. The limit is therefore socket-scoped under that load. A 2+2 control
  accepted both same-socket messages, correcting the broader prior claim that every second
  message is always ignored.
- Live-verified DAT-13 with an order-rotation control over the four front-month index futures.
  The first-subscribed future received 328 packets and every later future received 2 in both
  orderings; moving NIFTY from first to last moved dominance to BANKNIFTY. The 164× skew is a
  genuine subscription-order throttle/bias, not ordinary liquidity variation.

- Added historical bar fetch and local storage: Dhan minute and daily responses normalize into a
  strict versioned observed-bar schema on a stable on-disk layout. Bars only; no broker API
  offers tick-level history, so the tick tape is accumulated forward through DAT-02/DAT-05
  (D16). Tested.
- Added option-chain fetch and validation. Every security ID, underlying, expiry, strike, and
  side is checked against the same-date canonical Dhan master; unknown or mismatched IDs,
  crossed quotes, and non-IST timestamps fail closed rather than passing through. Tested.
- Added append-only tape recording and deterministic replay over the shared CON-01 format, so
  live, backtest, and research consume one tape. Dry-run verified against 21,279 existing live
  rows; no new live capture was performed for this acceptance.
- Added data-quality counters — crossed book, stale quote, invalid depth, sequence gap — written
  to a versioned derived audit artifact by the capture CLI, present even when zero rather than
  silently absent. Dry-run verified on synthetic faults.
- Added the per-broker instrument-master loader and mapping layer with daily refresh, since
  broker tokens are only guaranteed stable within a trading day. Tested.
- Added multi-socket capture planning for DAT-09 under the measured one-subscription-message-per-
  socket constraint and the permanent-retention decision. Tested.
- Added capacity, reconnect, and depth-skew probes (DAT-11/12/13): a binary search for the exact
  20-level per-message instrument ceiling, a reconnect test for
  whether the first-message limit is per socket or per account, and a same-liquidity control for
  the 200-level packet skew. DAT-11 is live verified at 50 instruments and DAT-12 is live
  verified as socket-scoped at 50+50; DAT-13 is live verified with order rotation.

### SUR-01, SUR-02, SUR-05, SUR-06, SUR-07, and SUR-08 — eSSVI surfaces

- Added one module-facing surface interface over CON-01 tape input and CON-03 frame output.
- Added synchronized multi-expiry eSSVI calibration with butterfly and calendar constraints,
  independent arbitrage checks, weighted fit/residual/stability diagnostics, and explicit
  strike/maturity support policy.
- Added arbitrage-rechecked temporal smoothing, caller-supplied staleness thresholds, and a
  fail-closed gate that prevents raw tick-synchronous fits from serving quoting consumers.
- Dry-run acceptance uses realistic synthetic option BBOs; live/historical DAT replay
  integration remains pending and is not represented as live verified.
- SUR-03 (SVI) and SUR-04 (SABR) remain deliberately blocked under D8 pending a concrete
  strategy need.

### INF-02 and INF-04 — typing marker and reproducible test invocation

- Added the `py.typed` marker and packaged it explicitly, so strategies that pin Shaurya (D5)
  receive the module's real type information instead of `Any`. Verified by installing the built
  wheel into a clean environment and type-checking a consumer against it.
- Fixed test collection depending on how the suite was invoked. Two test modules import from
  `scripts/`, which resolved under `python -m pytest` but not under the `pytest` console script;
  the repository root is now declared on pytest's path. Both invocations collect and pass.

### Specification

- Recorded D20: SIG's sampling clock, pooling coordinate, and prediction-horizon set are
  empirical questions resolved by measurement rather than specification constants. Each becomes a
  swept axis in SIG-19's trial log and is counted in SIG-12's multiple-testing grid. No package
  behaviour changes; SIG remains unimplemented.

### Test suite

- 54 tests before this session, 89 after. Strict mypy and ruff lint remain clean.

## v0.1.0 — 2026-08-18

The first release is `0.1.0`: Shaurya is already an installable dependency with live-verified
market-data foundations and tested contracts, but the frozen module is intentionally still
pre-`1.0.0` while most domain components and the native package remain unimplemented.

### DAT-01, DAT-02, and DAT-05-lite — initial Python distribution

- Built the installable `shaurya` package and reconciled the Mushin Gamma and Shoshin Dhan
  clients into one data-only client.
- Added supervised standard, 20-level, and 200-level WebSocket capture, versioned tape and
  instrument contracts, reconnect/resubscribe, heartbeat, sequence-gap semantics,
  permission-restricted manifests, and append-only JSONL output.
- The first accepted 20-level run recorded 232 packets in 30.001 seconds with zero reconnects;
  the later combined standard-plus-20-level run recorded 419 packets in 45 seconds with both
  required channels present.

### DAT-10 — 200-level deep-book capture

- Generalised the deep-book parser and added the 200-level endpoint and subscription shape.
- Corrected a silent zero-packet failure by using the endpoint's flat subscription message
  rather than the 20-level batch envelope; added a regression test.
- Live run `sha-20260818T092355.175225Z-d181b3ff` recorded 366 packets in 45.001 seconds and
  independently verified 200 bid plus 200 ask levels in the tape.

### MODULE_SPEC — frozen-requirement draft set

- Added the root `MODULE_SPEC.md` and 13 component specifications under `docs/module-spec/`.
- Mapped all 107 non-dropped task IDs exactly once to stable `REQ-*` rows with code, test, and
  output targets.

### CON-02, CON-03, CON-04, CON-06, CON-07, and CON-09 — shared contracts

- Added six strict, versioned Pydantic contracts, shared object-category and IST-causality
  types, and four committed cross-language JSON fixtures.
- Contract acceptance at implementation time was 52/52 pytest tests, strict mypy over 18
  source files, and a repository-wide Ruff pass.

### INF-02, INF-05, INF-07, and INF-09 — package and release foundation

- Reconciled the existing package metadata against VOLARB and Shoshin, retained the stricter
  setuptools/strict-mypy/Ruff configuration, and verified a clean editable install.
- Added the external-handle/700/600 secret policy and hardened ignore rules for credentials,
  runtime state, logs, and generated data.
- Established this changelog and the matching `v0.1.0` package/release version.
