# Shaurya Changelog

Shaurya uses semantic versioning. Each release records the implementation evidence relevant
to strategies that pin the package.

## Unreleased

### SIG-21 — exploratory future mid-price response scan `X-SIG21-DAT20-01`

- Added `scripts/sig21_exploratory_response_scan.py` and
  `src/shaurya/signals/deep_book_exploratory_response.py`, which attach the registered `H-SIG21`
  response convention to the already-registered construction detector's candidates over the two
  retained pre-registration `DAT-20` tapes and emit the complete 384-cell family in three risk-set
  arms, correlation tables, five negative controls and a power statement.
- **The scan can never be confirmatory and enforces that in code.** Both tapes were captured before
  the registering commit `f2cf6501` was pushed at 15:00:42 IST, so under `H-SIG21` §1.5 they were
  already permanently ineligible for the first outcome sample and under §1.2 their price paths were
  already excluded from SIG-21 inference. Every artifact carries `exploratory_scan_id`,
  `confirmatory_eligible: false`, the source tape SHA-256s and the §1.5 justification. Refusals:
  a confirmatory or economic framing is rejected before a file is opened; any tape outside the two
  pinned SHA-256s is rejected; any threshold provenance other than `in_sample_exploratory` is
  rejected; anything less than the complete 384 cells is rejected.
- Episode-count-versus-selectivity curve, pooled and per construction cell, over fourteen
  within-sample cutoffs. Pooled, the primary risk set stays at 2 episodes from the 50th percentile
  through the registered 99.5th and reaches 39 of a 118 ceiling only at 99.9%; per construction cell
  it is 321 at 99.5% and 129 at 99.9%, peaking at the 95th percentile with 608. Magnitude ties make
  the nominal 99.5% cutoff retain 5.0% of candidates rather than 0.5%.
- `(Z, h2)` window decomposition: at 99.5% a `Z=0.5/h2=1` cell has 260 non-overlapping episodes
  under its own 1.5 s window against 2 under the 11 s family maximum. Reported as a diagnostic; the
  registered 11 s window is used unchanged for every estimate.
- Complete 384-cell family in `primary_non_overlapping_episodes`,
  `secondary_all_event_overlap_robust` and `event_minus_matched_control` arms, reported side by side
  with two effective sample sizes each — a deterministic episode count and an estimated
  variance-inflation figure. The secondary arm is never promoted to primary. The registered
  `hac_newey_west_mean_difference` estimates the paired control arm and is cross-checked against it.
- Matched quiet controls with every failure explicit: **zero quiet control instants exist at the
  99.5% threshold**, so the registered primary estimand is undefined for 192 cells; 313 survive at
  99.9%. The `VOL-04` regime stratum is unidentified here, so matching is on three registered strata.
- All five registered negative controls over the complete family. Three fire in 31–41% of cells
  against a 5% null, so the raw response arms are measuring the session's drift rather than the
  events; the quiet-versus-quiet placebo is clean at 0/384.
- Power statement measured against the registered gates: no cell in any arm meets the 0.25-tick mean
  MDE gate on a credible sample size, and the apparent passes are Bartlett variance collapse at
  n = 1. The gate needs 26,000–149,000 effective episodes per cell against a 40,900-episode ceiling
  for the entire registered 20-session evaluation sample.
- **Fixed a defect in `build_depth20_response_labels` found on its first contact with real tape.**
  With no coverage bound, an endpoint past the last depth20 observation silently resolved back to
  that observation: on the `DAT-20` tapes 306 cells were truncated, 45 of them reporting an exact
  0.0-tick response over a *negative* realised horizon. Added an optional `coverage_end_ts_ns`
  parameter which refuses such cells with `endpoint_beyond_coverage`; omitting it preserves the
  previous behaviour byte-for-byte, so no existing caller changes. Three regression tests.
- Added `depth20_midpoint`, `outer_price` and `edge_distance` as public accessors over logic that
  was already present, so the response path and the rim diagnostic reuse the registered rules rather
  than reimplementing them.
- Added `tests/test_sig21_exploratory_response.py` (76 tests) covering every protocol refusal, the
  coverage-guard regressions, the selectivity and window diagnostics, the HAC estimators, the sign
  convention, complete-family emission, and a regression proving the quiet-episode placebo is not
  forced to zero by construction. Full Python suite 343 tests; Ruff and strict mypy clean.
- Report: `docs/SIG-21-EXPLORATORY-RESPONSE-2026-08-19.md`, including a candidate model proposal
  requiring its own `H-SIG21C-*` registration and a §14 change-control proposal on the §6
  primary-risk-set definition awaiting Aryan's approval. Artifacts:
  `artifacts/sig21-exploratory-response/`. **The immutable `H-SIG21` registration is unchanged and
  no result about predictability exists.**

### SIG-21 — outcome-blind construction replay and the basic 32-cell support grid

- Added `scripts/sig21_construction_replay.py` and
  `src/shaurya/signals/deep_book_construction_grid.py`, which replay the already-registered
  `H-SIG21` construction detector over retained depth200 futures tape and emit the complete
  construction support grid. The registered detector's semantics are reused unchanged.
- The registered 384-cell family is decomposed explicitly: only `8 atomic types x 2 sides x
  2 distance bands = 32` cells are determined by construction; the threshold, `Z` and `h2` axes
  multiply the same support and are not measurable outcome-blind. The artifact always emits all
  32 cells, including empty ones.
- Replayed both retained `DAT-20` NIFTY front-month futures tapes (21.76 minutes, security
  `58072`). All 32 construction cells are populated: 40,724 candidates in 5,325 bursts, 99.82% of
  transitions valid. The registered 11-second non-overlapping episode rule is the binding
  constraint on the primary risk set — the largest inter-burst gap is 0.807 s, so both tapes
  collapse to 2 episodes and the risk set is capped at `floor(22,500/11) = 2,045` per session.
- Added an outcome-blind window-edge diagnostic: 41.4% of candidates lie within Rs 1 of the
  outermost occupied price on their own side (76.9% of ask removals, 72.5% of ask additions),
  so the four largest cells are substantially the 200-level window's rim shifting rather than
  interior far-book activity, while the quantity and order-count families are genuinely interior.
  The registered §3 boundary-churn rule is applied exactly as written and no candidate was
  reclassified; this is reported so the grid is read correctly.
- The past-only baseline layer is reported, not fabricated: every registered key is
  `baseline_insufficient` because no completed prior session exists, no candidate was scored and
  no threshold was estimated. Session-scale projections are labelled scenario-based with their
  linear-rate assumption and mid-morning-window bias stated.
- `H-SIG21` §1.2 is enforced in code, not only in documentation: the entry point refuses any
  outcome-bearing request before opening a tape, records `protocol_id`, `sample_role`,
  `outcome_join_allowed=false` and each input tape's SHA-256 (cross-checked against the capture
  manifest), and verifies the instrument is a NIFTY future. No response, return, midpoint,
  markout or label is computed or read anywhere.
- Added `tests/test_sig21_construction_replay.py` (49 tests) covering deterministic fixture
  aggregation, empty-cell emission, protocol refusal, SHA recording and manifest agreement, and a
  regression that replaces `build_depth20_response_labels` with a raising stub to prove it is
  never called. The full Python suite passes 255 tests; Ruff and strict mypy remain clean.
- Report: `docs/SIG-21-CONSTRUCTION-REPLAY-2026-08-19.md`. Artifacts:
  `artifacts/sig21-construction-replay/`. The immutable `H-SIG21` registration is unchanged.

### Depth-tier scope by instrument class (D33)

- Bound the depth tier to the instrument class: the 200-level endpoint is restricted to futures and
  equity books, and option books are capped at 20 levels module-wide.
- Enforced at the single socket-construction choke point in `DhanLiveStream.run` via
  `DEPTH200_ELIGIBLE_KINDS`, so no caller can bypass it, and repeated as an early, explicit failure
  in the capture CLI before credentials are read or a socket is opened.
- `--sig21-calibration` now also requires a future, matching the `H-SIG21` registration, and capture
  metrics record the instrument kind, the eligible depth200 kinds and the option depth ceiling.
- Audit note: depth200 was **not** enabled by default anywhere before this change
  (`DhanStreamConfig.enable_200_level_depth` was already `False`, `--enable-depth200` was already
  opt-in, the DAT-09 plan's `depth200_security_ids` already defaulted to empty, and the ANL-03
  option-chain capture uses the 5-level Quote/Full channel). The real gap was the missing
  instrument-class guard: depth200 eligibility was filtered on exchange segment only, and every NSE
  option is `NSE_FNO`.
- Added `tests/test_depth_tier_scope.py`. The full Python suite passes 206 tests; Ruff and strict
  mypy remain clean.

### SIG-21 — depth200 calibration scope lock (D32)

- Recorded Aryan's binding clarification that SIG-21's differentiating treatment is the
  price-keyed far **depth200** ladder. Depth20 is retained only for the later BBO midpoint response
  and registered near-book controls; it can never originate or substitute for an anomaly.
- Added an enforced `--sig21-calibration` profile to the Dhan capture CLI. It refuses runs without
  depth200, with depth20 disabled, or with a requested duration shorter than the 22,500-second
  regular NSE session, and records the channel roles, calibration-only status, registration
  commit, 384-cell family and `outcome_join_allowed=false` in capture metrics.
- Added a detector regression rejecting depth20 states and protocol tests for every capture gate
  and the exact metadata contract. The full Python suite passes 197 tests; Ruff and strict mypy
  remain clean.
- Added `docs/SIG-21-CALIBRATION-RUNBOOK.md` and replaced the reset handoff. The pushed 384-cell
  registration remains immutable: the five calibration sessions estimate support and power, not
  a preferable grid.

### Traceability repair — follow-up tasks added after the original module-spec draft

- A full ID-set audit triggered while adding `SIG-21` found that four previously opened,
  non-dropped follow-up tasks — `DAT-18`, `DAT-19`, `DAT-20`, and `ANL-05` — had no corresponding
  `REQ-*` row. Added `REQ-DAT-18/19/20` and `REQ-ANL-05`, then mapped `SIG-21` as
  `REQ-SIG-21`. The resulting trace is exact: 119 task IDs, 3 intentionally dropped, and all
  **116 non-dropped task IDs mapped once with no duplicate or orphan requirement IDs**.

### DAT-20 — depth200 activity thinning versus feed loss (H-DAT20)

- Recorded Aryan's interpretation correction as D28: the quiet far depth200 tail is retained as
  an anomaly-monitoring research object, not dismissed because ordinary activity is sparse.
  DAT-20 proves observability, not that rare deep events forecast price. Opened `SIG-21` as the
  next pre-registered task to test deep-book anomalies against future mid-price responses with
  causal baselines, overlap/dependence controls, full-grid multiplicity and a multi-session
  sample/power gate before outcomes are inspected.

- Pre-registered `H-DAT20` under `D22` at `bc458d4`, before the analyser existed (`fedb2b2`)
  and before any capture ran. §1 of the evidence document has not been edited since.
- Captured two clean 660-second three-tier NIFTY August future runs (Standard/Full + depth20 +
  depth200 simultaneously, one process writing one tape so every receive timestamp shares one
  clock): 11,770 and 11,802 rows, zero reconnects, zero heartbeat timeouts, 65/65 heartbeats per
  channel. Held the four-socket budget exactly against the concurrent `ANL-03` dashboard, with
  sequential bring-up recorded per run.
- **Confirmed the central claim: depth200's skips are empty.** Holding span duration fixed at
  approximately 400 ms, the rate at which a witness tier shows a state depth200 never published is
  statistically indistinguishable between spans depth200 published nothing inside and spans it did
  — 10 of 10 comparisons non-significant across both runs, smallest p = 0.067. The pre-registered
  skip-versus-control contrast appeared to fire on the deep ladder but was entirely a window-length
  confound (400 ms skip windows against 200 ms controls) and vanishes under duration matching.
- Confirmed top-of-book consistency: level-1 price agreement 98.00%/99.54% against depth20 and
  96.46%/99.00% against Full under the phase-tolerant rule, clearing the pre-registered 95% bar in
  both runs. Median missing price points is zero in every containment direction, and all three
  tiers agree on the spread distribution to within 0.04 rupees at the mean.
- Confirmed activity thinning only after correcting the measurement: the pre-registered
  position-keyed change rate *rises* with level index (Spearman +0.41 to +0.91) because one
  insertion cascades onto every deeper position, while the price-keyed rate keyed to the same-side
  best quote decays as predicted (Spearman −0.64 to −0.93, both runs, both sides). Activity per
  price point peaks a few rupees behind the touch rather than at it.
- Produced the direct `DAT-09` width-versus-depth input: 86.6–99.0% of all book events fall within
  Rs 20 of the same-side best quote, which is a median of 74–90 occupied levels. Beyond that a price
  point runs at 0.05–0.08/s on the bid and 0.002–0.003/s on the ask against 1.2–2.8/s near the
  touch. depth20's 20 levels reach only Rs 7.4–10.1 from mid and capture 57–84%.
- Settled the occupancy question by measurement: all 200 levels are always populated with zero
  padding, and the median span is Rs 136.0–136.8 from deepest bid to deepest ask — about 3.4x the
  ±Rs 20 working assumption and 6.8x the 200-contiguous-tick arithmetic — because only 13.3–18.4%
  of the 0.05-rupee tick grid inside the span is occupied.
- Fixed a real measurement bug found mid-analysis and disclosed it: the Full packet encodes its
  five-level prices as IEEE-754 binary32 while both depth channels use binary64, so exact float
  equality initially reported 0 of 791 price agreement for reasons unrelated to book content.
  Prices are now quantised to two decimal places, exact for the 0.05-rupee tick, with regression
  tests in both directions.
- Added `DhanStreamConfig.channel_start_stagger_seconds` for sequential channel socket bring-up
  under a hard socket budget; the default of 0.0 preserves the previous simultaneous behaviour.
- `F1`/`F2` are **not discriminated**: no channel in this tape carries an exchange timestamp or
  source sequence, so snapshot-instant alignment is unidentified and the residual 1–6% (bid) /
  6–18% (ask) cross-tier level difference cannot be attributed to phase or to content. The upstream
  publication mechanism remains **unidentified**, unchanged from `DAT-17`.
- **`DAT-17`'s one-instrument-per-socket recurring depth200 ceiling is unaffected and stands
  unchanged.** DAT-20 tested a single subscribed instrument on a dedicated socket and found no
  evidence bearing on the ceiling.

### Session planning — 2026-08-19 afternoon agenda opened

- Opened `DAT-18` (consolidated multi-tier feed interpretation), `DAT-19` (storage and
  retention architecture) and `ANL-05` (dashboard visual design), all scheduled by Aryan for
  the 2026-08-19 evening session with discussion explicitly preceding decision.
- Recorded the `ANL-03` continuing afternoon run (12:04 to approximately 15:47 IST, 452 NIFTY
  instruments) which supplies the afternoon and market-close coverage the morning window
  lacked, and measured its tape cost at approximately 40 MB/minute — the concrete number
  forcing `DAT-19`.
- Recorded a provenance caveat on `DAT-17`: two agents ran the task concurrently from two
  OpenClaw sessions, both completed, the tree was deduplicated at `b4a2975`, and the socket
  overlap of approximately 35 seconds did not affect the authoritative capture.

### DAT-17 — depth-tier cadence and operational bounds

- Live-measured depth200 twice on NIFTY August futures in independent 600-second,
  zero-reconnect captures: both runs produced 4,980 rows and exactly 2,491 receive-timestamp
  bursts (4.1588–4.1589/s), with gap p05/p50/p95 approximately 197/201/401 ms and two rows
  per ordinary burst.
- Classified depth200 as a quantized, skip-prone approximately 200 ms base clock rather than
  depth20's fixed 500 ms metronome: the depth200 p95 is approximately two base ticks and its
  observed maxima were 602–603 ms. The physical publication/aggregation mechanism remains
  unidentified because exchange timestamps and source sequences are absent.
- Reproduced DAT-13's first-subscription throttle with timed evidence. Position 1 delivered
  742 packets / 372 receive timestamps over 91.003 s; positions 2–4 delivered only an initial
  two-packet pair and then no update for approximately 89.9 s. The observed usable recurring
  ceiling is one depth200 instrument per socket. A 600.987 s replication strengthened this:
  position 1 delivered 4,984 packets / 2,493 timestamps, while positions 2–4 again delivered
  two bootstrap packets each and then remained silent for 599.789 s.
- Verified from retained healthy tapes that all 730/730 NIFTY and 993/993 BANKNIFTY Full rows
  carry complete five-level books, so the block is republished on the dispersed Full clock
  (1.217–1.656/s), not a separately observable clock.
- Applied D27 pairwise: Full binds Full+depth20 and Full+depth200 (median 557–874 ms; p95
  guardrail 1,112–1,141 ms), while depth20 binds depth20+first-position-depth200 (median
  501 ms, p95 506 ms). Later-position depth200 has no finite recurring horizon and is
  operationally inadmissible.

### ANL-03 — live implied-volatility surface dashboard (surface scope only)

- Added a read-only surface dashboard and server (`shaurya.analytics.{forward,universe,
  surface_feed,dashboard,server}`, `shaurya.cli.{capture_chain,surface_dashboard}`) serving
  `GET /`, `GET /api/state` and `GET /api/history` on `http://127.0.0.1:8765/`. No write
  method is implemented and no order path is imported, per D19 and `ANL.md`.
- Drove it from a DAT-05 replay first and then from one live Dhan Quote/Full connection:
  116 snapshots over 11:27–11:37 IST 2026-08-19 on 452 NIFTY instruments, 116/116 fits
  converged, 0 reconnects, aggregate feed age p50 4.7 ms / p95 30.8 ms, fit duration p50
  0.159 s, and `SUR-05` butterfly and calendar checks passing on all 116 snapshots.
- Feed death is shown, not inferred: health is sampled on every dashboard read rather than
  only when a fit lands, so a stopped feed keeps ageing on screen. A 45 s post-stream window
  rendered status DEAD, 0.0 packets/second, and three named threshold breaches while the last
  good surface remained drawn.
- Staleness thresholds are calibrated to DAT-16's measured cadence and to this run, not
  chosen by taste: feed slow/dead 1 s / 2 s, fit stale 20 s against a measured 5.16–5.20 s
  fit gap, and `SUR-07` surface staleness 480 s because surface age is the age of the oldest
  contributing quote (measured p50 200 s, p95 421 s on a 452-instrument chain).
- Forward source is a stated model choice per expiry — traded future where the expiry matches,
  put-call parity otherwise — carried as a `CON-06`/§7.1 `ObjectLabel` with construction,
  assumptions and limitations, and displayed on screen.
- Measured the Quote/Full (`RequestCode` 21) instrument ceiling empirically rather than
  assuming it: 402, 1,203, 3,003 and 5,538 instruments on one socket all returned packets for
  every requested instrument, with zero silent instruments and zero reconnects. The ceiling is
  a **lower bound of 5,538** — past Dhan's documented 5,000 — and unlike the 20-level depth
  channel, multiple subscription messages on one Quote/Full socket all take effect.
- Scope limits recorded rather than generalized away: the ANL-01/ANL-02 P&L, markout and
  reporting views are not built; no live reconnect, no observed arbitrage violation, no
  non-NIFTY underlying, and no afternoon or expiry-day session were exercised.


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
