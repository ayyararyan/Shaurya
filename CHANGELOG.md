# Shaurya Changelog

Shaurya uses semantic versioning. Each release records the implementation evidence relevant
to strategies that pin the package.

## Unreleased

### DAT-19 — canonical NSE server placement

- Added one central fail-closed archive resolver for the verified IEX SMB share at
  `/Volumes/Aryan/NSE`.
- Standard Dhan and option-chain DAT capture entry points now default to
  `YYYY-MM-DD/raw` in IST and create the companion `metadata`, `indexes`, and `derived` lanes.
- Refuse the production default when `/Volumes/Aryan` is not the expected
  `//Aryan@172.20.10.38/Aryan` SMB mount, preventing an unmounted-volume local fallback.
- Reject local output overrides unless the caller also supplies the named controlled-test escape
  hatch. D43 removes the former surface-owned capture path; surfaces follow the same DAT dataset
  written to this archive.

### D43 — DAT single market-data access plane

- Added strict broker-neutral `DatasetRequest` and immutable `DatasetHandle` contracts. Consumer
  identity is audit metadata rather than acquisition identity, so compatible SUR, SIG and ANL
  requests resolve to one active or completed dataset.
- Added one flock-serialised append-only DAT catalogue and cross-process acquisition claim.
  Duplicate compatible capture attempts return the existing active handle and do not open a
  second Dhan stream; dead producers are never reused.
- Added permanent warm JSONL storage with published hashes, an incremental seek index for bounded
  time/channel/instrument retrieval, verified lossless gzip cold archives, and streaming adoption
  of legacy tapes. Tape, index and archive tampering fail closed.
- Moved growing-file complete-line transport and option-chain universe selection into DAT.
  Surface/eSSVI and OFI dashboards now resolve DAT handles for replay/follow; the OFI full-session
  controller resolves its capture from the catalogue instead of globbing raw run directories.
- Preserved all existing tape rows, surface fits, OFI estimators, registered samples and causal
  semantics. The change is ownership and transport only; it adds no order path.
- Acceptance: all 705 tests passed; repository-wide Ruff, strict mypy on 70 package source files
  plus the changed full-session controller, compileall and diff checks are clean. Production-volume
  shared follow/archive remains an explicit operational verification rather than an implied claim.

### D41 — mid-return lags versus CCZ OFI, hypothesis freeze

- Added agreed claim `EF-11/H1` and froze
  `docs/D41-MID-LAG-OFI-INCREMENTAL-SPEC-2026-08-20.md` before executing the new comparison.
- The declared future grid is 0.5/1/2/5/10/20/30 seconds after a 0.5-second gap. It compares only
  seven past displayed-mid returns, ten-level depth-scaled CCZ OFI alone, and their exact union.
- Bound identical chronological held-out rows, a 30.5-second embargo, training-only ridge choices,
  absolute OOS R², HAC Diebold--Mariano, nested Clark--West and Holm inference. D41 is permanently
  retrospective on today's immutable 15:42 partial-session tape and does not alter D39/D40.
- Implemented the 126-cell future panel plus six separate contemporaneous checks and executed it
  from pinned commit `a512fbe` on the frozen tape. Same-window OFI OOS R² rises from 1.3401% at
  0.5 s to 24.6372% at 30 s; all six construction checks are Holm-significant.
- Past returns are weak alone (lag-bank OOS R² −0.6151% to +0.4380%; no adjusted hit). OFI has
  higher point OOS R² in 35/35 cells. OFI adds beyond lags in 35/35 cells and survives the full
  35-cell Clark--West/Holm family in all 35.
- At the pre-named 10-second OFI window, lags also add beyond OFI at all seven horizons; the union
  reaches 4.9297%/4.9301% OOS R² at 20/30 seconds. The result rejects redundancy on this tape.
- Added the report, compact committed result and tomorrow's post-D39/D40 unchanged validation step.
  Acceptance: 679 tests, Ruff, strict mypy on 66 source files, compileall, artifact parity, row,
  feature-union, multiplicity and hash gates all pass.

### D40 — displayed-mid OFI horizon extension machinery

- Froze `docs/D40-OFI-HORIZON-EXTENSION-SPEC-2026-08-20.md`: exact D39 `C8`, `M=10`, trailing
  10-second depth-scaled CCZ OFI, displayed-mid returns only, extended to 10/20/30/45/60/90/120
  seconds after the unchanged 0.5-second causal gap.
- Parameterised the canonical observation builder so explicitly requested response horizons are
  additive to the original map, preserving predictor features, the anchor universe and the D39
  training boundary.
- Added a hard leakage guard requiring the chronological embargo to cover the causal gap plus the
  longest response. D40 therefore uses 120.5 seconds while D39's original grid remains unchanged.
- Added a fixed-scope runner that emits a full research artifact plus a compact C8 absolute-OOS-R²
  summary and refuses an incomplete or changed seven-cell grid.
- Added focused regressions for custom response materialisation and the long-horizon embargo gate.
- Corrected run `X-D40-OFI-HORIZON-EXTENSION-2026-08-20` estimated all 7 cells. Absolute OOS R²
  rises from **7.4037% at 10 s to a 15.7793% tested peak at 20 s**, then turns **−0.4698% at
  30 s** and remains negative through 120 s (−22.6148%). The curve is not monotone beyond 10 s.
- Invalidated and isolated an earlier artifact that let custom response horizons replace the
  default response map and thereby shift the 70/30 anchor boundary. The corrected additive
  construction preserves all D39 anchor timestamps; a direct-invocation regression and an
  anchor-sequence regression now prevent both defects from recurring.
- Added the full methodology/result report, machine-readable compact result and a pre-written
  2026-08-21 prompt to validate the 20-second peak/30-second break on the untouched full session.
- Final acceptance: 32 focused tests and 676 whole-repository tests passed; whole-repository Ruff,
  canonical strict mypy over 65 source files, compileall, artifact/schema parity and hash checks
  all passed.

### ANL-07 — surface-relative executable option-mispricing monitor

- Added a read-only detector that never compares a contract with a surface it helped fit.
  Five deterministic strike folds exclude both CE and PE at each held-out strike; candidates
  that survive empirical uncertainty, costs and BH-FDR receive a second exact leave-strike
  refit before they can enter the episode state machine.
- Added fresh-quote and observed-support gates, matching-future or robust held-out parity
  forwards, Black-76 fair prices, empirical past-only residual bands, forward/asynchrony
  stresses, explicit dated tick/lot provenance, direction-specific verified turnover rates,
  visible exit/hedge slippage, displayed-one-lot and positive-net-edge gates.
- Added causal two-frame confirmation and correction. First-seen time is retained through
  confirmation; unavailable/stale/missing/unsupported paths are censored rather than called
  corrected. Owner amendment 1 replaces misleading market/surface labels with signed
  target-option/reference-market endpoint accounting: entry gap, both contributions, net gap
  closed, exact identity residual, closing gate, and target-option-led/reference-market-led/mixed
  attribution are carried in every episode and rendered in both tables.
- Owner amendment 2 removes raw five-second fits from opportunity identification. Every held-out
  fold now uses a causal 60-second-half-life eSSVI parameter smoother keyed to the fit decision
  clock, requires twelve consecutive smoothed frames, rejects a twelve-frame fair-IV range above
  0.10 volatility points or a raw-versus-smoothed distance above 0.10 points, and keeps the exact raw
  leave-strike fit as a direction/agreement check rather than letting it replace the stable
  benchmark. The displayed ANL-03 smoother now also uses decision time, fixing its live
  `raw_unsmoothed` fallback when the oldest contributing quote timestamp did not advance.
- Episode interpretation is now fixed-entry and target-specific: the entry after-cost gap is
  frozen, only two frames in which the target executable quote closes that gap are `corrected`,
  and reference-led, mixed, or stability-lost disappearances are `invalidated`. Dashboard/API
  expose raw/smoothed IV, their distance, twelve-frame range, smoothing count/stability, the frozen
  target requirement, and corrected/invalidated/censored outcomes.
- Added full policy and lifecycle state to every surface snapshot, `/api/state`, and
  `/api/history`; the ANL-05 screen now has full-width Active confirmed and Recently
  corrected/invalidated/censored tables below the surface. The monitor is explicitly surface-relative,
  estimated and research-only, with no signal, fill, arbitrage, latent-value or order claim.
- Frozen specification: `docs/SURFACE-MISPRICING-SPEC-2026-08-20.md`. Synthetic acceptance
  covers IV inversion, warm-up, exact cheap confirmation, two-frame activation/correction,
  duration/driver, one-lot rejection, censoring and the no-order dependency boundary. Evidence:
  41 focused tests and 545 full-suite tests pass; Ruff, strict mypy (59 source files), and
  compileall are clean; a headless-browser probe rendered the warming state and both lifecycle
  tables. Real retained-tape replay and live verification remain pending.
- Owner-amendment validation: 35 focused dashboard/detector tests and 549 full-suite tests pass;
  Ruff, strict mypy (59 source files), and compileall are clean. The live restart and rendered
  signed traces are a separate deployment check, not a profitability or fill claim.
- Owner-amendment-2 validation: 47 focused surface/smoother/detector/dashboard tests and 554
  full-suite tests pass; whole-repository Ruff, strict mypy on 59 source files, compileall, and
  diff checks are clean. Regression coverage includes fixed source timestamps with advancing fit
  decisions, twelve-frame warm-up, abrupt reference rejection, frozen target correction, and
  reference-only invalidation. Live restart and fresh market outcomes remain a separate gate.
- The first live calibration under the superseded 30-second/six-frame defaults admitted the same
  1 September 24450 CE twice; both episodes invalidated reference-led and never met the frozen
  target test. They are retained as calibration evidence, not opportunity results. The binding
  one-minute defaults above and mandatory twelve-frame re-warm after invalidation prevent that
  immediate transient re-entry; their replacement live run is a separate acceptance gate.
- Owner amendment 3 moves the identification and lifecycle state from absolute option-price
  rupees to executable implied volatility. The ask IV is tested below a held-out fair-IV lower
  boundary for cheap contracts and bid IV above the upper boundary for rich contracts. The
  entry executable IV, fair-IV boundary, uncertainty calibration and after-cost IV target are
  frozen; only target executable-IV convergence can correct an episode. Current Black-76 rupee
  edge remains the positive-after-cost execution overlay, so a forward move cannot masquerade as
  correction and a statistically unusual but uneconomic residual cannot activate.
- Replaced hard moneyness/liquidity residual buckets with a past-only Gaussian-weighted nearest-
  neighbour IV estimator within expiry and CE/PE. It conditions continuously on log-moneyness and
  log-relative spread, exposes neighbour and Kish effective sample sizes, converts tick,
  forward-band and asynchrony price stresses into IV-equivalent widths, and excludes every current
  outside-IV-band observation from its own causal history.
- Added signed IV-gap accounting and a frozen-entry-delta executable-quote markout. The latter is
  explicitly scenario-based: it uses current liquidation BBO, a single frozen Black-76 delta,
  observed forward change and visible turnover/slippage assumptions; it is not a fill, dynamically
  rehedged P&L, or order-authority claim. The dashboard/API expose the IV band, continuous
  uncertainty support, IV target/reference contributions, rupee overlay and delta proxy together.
- Owner-amendment-3 pre-live verification: 56 focused surface/detector/dashboard tests and 558
  full-suite tests pass; whole-repository Ruff, strict mypy on 59 source files, compileall and diff
  checks are clean. Regressions cover removal of the former 1% spread-bucket discontinuity, causal
  exclusion of a current outside-band residual, cache invalidation, pure-forward price movement,
  IV correction despite a falling absolute option price, signed cheap/rich markout arithmetic,
  dashboard/API schema, reference warm-up/invalidation and the no-order dependency boundary. A
  six-key, fully capped 120,000-sample performance gate completed all 450 continuous-neighbour
  queries in 0.18 seconds. Replacement live verification remains separate.

### `X-OFI-DASHBOARD-2026-08-20` — dynamic read-only OFI horse-race dashboard (`ANL-06`)

- Added one file-only engine with deterministic pinned-tape `replay` and read-only growing-JSONL
  `follow` modes. Neither mode imports a broker socket, credential or order path. Complete lines
  alone are consumed; an EOF-torn line stays buffered, malformed lines are counted, and a
  byte-by-byte tail produces the same rows as a completed-file read.
- Added the complete 175-cell M0–M6 by h1/h2 0.5/1/2/5/10-second grid by calling the canonical
  signal feature and fit implementations. The dashboard supplies the frozen epoch-safe response
  endpoints through the canonical midpoint-return helper, including the exact past mirror ending
  at `t-Z`; it does not restate a predictor formula.
- Added a one-way walk-forward ratchet with expanding training, per-horizon
  `max(120 s, Z+h2)` embargo, disjoint fixed-duration test blocks, longest-response closure and
  training-only standardisation/Ridge selection. Each held-out prediction is accumulated once;
  the stationary bootstrap treats blocks as separate strata and cannot splice them.
- Added the ANL-05 muted light/dark shell and four GET/HEAD-only routes: `/`, `/api/state`,
  `/api/history`, `/api/cells`. Raw and placebo-benchmarked block/accumulated scores remain
  simultaneous; negative, `WARMING`, `INSUFFICIENT` and unidentified M2 cells remain visible;
  brick is reserved for past-mirror increment at least as large as future increment. The screen
  also keeps 175-cell chance expectation, BH-FDR, green/leader churn, HAC/bootstrap support and
  collinearity warnings visible or retrievable with object-category labels.
- Every completed cadence appends all 175 cell records and a compact deterministic summary. Two
  full default replays of pinned DAT-20 SHA `751ee15a…e0` produced byte-identical cell artifacts
  (SHA-256 `20b16586c766be7e2abfebbfec023190c438199fc554bd0ee200852fd798419b`);
  an equivalent fixed split matched all 175 canonical offline OOS-R² scores exactly (maximum
  absolute difference 0 at tolerance `1e-12`).
- Acceptance: 18 focused dashboard tests and 539 full-suite tests pass. The leakage probe detects
  the synthetic future-only feature and gives the past-only feature a placebo-benchmarked
  increment at or below zero. Light/dark and degraded-state headless screenshots were inspected.
  Evidence level is **Dry-run verified**, not Live verified: no growing production tape has been
  attached and no live score is claimed. `H-SIG21.md` is unchanged.

### `X-SURFACE-FUT5-20260819-06` — displayed eSSVI versus next five-second futures move

- Added a frozen, permanently exploratory replay of the three-expiry five-second displayed eSSVI
  surface on the pinned full-session ANL-03 Quote/Full tape, joined to the front NIFTY future's
  `t+0.5 s` to `t+5.5 s` BBO-mid move.
- Added exact theta/rho/psi, ATM IV/skew/curvature, changes, velocities and adjacent-expiry term
  features; a separately identified fixed-schema quality block; exact five-level LOB state; and
  canonical CKS plus price-keyed five-level OFI without duplicating either transition formula.
- Added the same-sample N/S/SQ/L/O/LO/LOS/LOSQ Ridge horse race, train-only preprocessing and inner
  CV, 120-second embargo, held-out halves, full Pearson/Spearman HAC/FDR screen, paired Newey-West /
  stationary-bootstrap / non-overlap inference, past mirror, same-window diagnostic, 300-second
  no-wrap placebo, 480/240-second freshness and explicit surface collinearity diagnostics.
- Complete replay: 2,579 common rows, 1,805 train, 23 embargoed and 751 test. Future OOS R² is S
  −0.24%, L −0.74%, O −2.01%, LO −2.90% and LOS −6.08%; adding surface to LO worsens R² by 3.17
  points. No held-out surface correlation survives BH-FDR. Past/same OFI is much stronger, so no
  future predictive claim is promoted.
- Added focused regression coverage, 39-row frozen-spec traceability, a compact result/model bundle
  and a plain-English report. Full artifacts remain gitignored and hash-pinned. No live system,
  broker, credential, capture, subscription or order path was touched.

### Dated NSE F&O clock and full-session OFI replication

- Added a dated NSE equity-derivatives clock: 09:15–15:30 before 2026-08-03 and 09:15–15:40
  from that date. Current full-session duration is 23,100 seconds; surface expiry close, SIG-21
  capacity calculations, capture validation and storage planning now consume the shared helper.
- Added pre-data `H-SIG21-A2` without editing the immutable registration. Current 11-second
  opportunity ceilings are 2,100 per session, 10,500 over calibration and 42,000 over evaluation;
  registered 30-minute bins retain the short 15:30–15:40 final bucket.
- Added the protocol-locked, read-only `R-OFI-FULLSESSION-2026-08-20` capture profile and durable
  controller for Standard/Full + depth20 + depth200 on the unique same-day NIFTY front-month
  future. Acceptance is based on actual opening/closing publications and complete depth books,
  not requested duration.
- Added memory-bounded burst/state construction and full-session replay modes for the scalar OFI,
  exact CKS L1 and complete M0–M6 horse-race scans. The two pre-named leads are reported before
  full-grid reranking; one-tape cross-stability is unsupported and the 30-second gate stays closed.
- The replication is selection-aware and exploratory, is not `H-SIG21`, has no order authority,
  and cannot be promoted to a signal or confirmation.
- Live execution on 2026-08-20 failed before capture because the generated runner invoked the
  controller as a file and its repository-namespace import was unavailable. The controller now
  supports both direct-script and module invocation, with a cross-working-directory regression
  test. The registered run missed opening coverage and produced no analysis; a separately marked
  late-session partial tape is not substituted for it.

### `X-OFI-HORSERACE-DAT20-05` — causal-alignment short-horizon predictor horse race

- Added one common-sample comparison of depth only, static queue imbalance, identified signed
  trades, canonical raw CKS L1 OFI, regularised seven-band price-keyed OFI, causally depth-adjusted
  multi-level OFI and a regularised combined model over h1/h2 0.5/1/2/5/10 seconds.
- Reuses `cks_l1_transition` from `X-CKS-L1-OFI-DAT20-04`; no duplicate CKS formula. M2 uses only
  capture-time `quote-mid-tick-v1` / `latest-complete-depth-before-print-v1` non-coalesced,
  non-degraded last prints and becomes explicitly blocked if either tape lacks minimum support.
- Added training-only standardisation and three expanding inner folds over a frozen six-alpha Ridge
  grid, per-tape support/reproduction, Newey-West/stationary-bootstrap/non-overlap inference, full
  past mirror, same-window diagnostic, normalised trade/CKS sub-arms, M4-vs-M5 increments, band
  collinearity diagnostics and 125 leave-family-out M6 ablations.
- Complete execution: 5,210 common anchors; 3,646 train, 960 embargo, 604 test; 175 future and 175
  past primary cells; 50 normalised sub-arms per direction; 35 same-window cells. M2 retained 191
  qualified packets and excluded 117 coalesced plus 2 degraded/unclassified packets.
- No robust primary winner. Reproducing primary leaders are M6 at 0.5–2 s, M4 at 5 s and raw M3 at
  10 s, but none clears all three dependence checks and short-horizon past mirrors are stronger.
  Depth-normalised CKS is the strongest robustness lead at h1=2 s/h2=2 s (+6.204 pp over M0;
  +8.262/+3.115 pp by tape).
- The frozen 30-second gate fails: raw M3 passes pooled/per-tape fit and the past-mirror condition at
  h1=0.5 s/h2=10 s but its actual standardized coefficient flips sign across tapes. A regression
  test prevents mechanically nonnegative fitted-family covariance from substituting for coefficient
  direction. No 30-second cell is fitted or ranked.
- Added `scripts/ofi_horserace.py`, focused tests, frozen spec, full plain-English report and compact
  result/hash summary. Artifacts remain gitignored. Exploratory only; `confirmatory_eligible=false`;
  immutable `H-SIG21` unchanged.
- Completion audit repair: exact classifier and alignment versions are now enforced with separate
  missing/wrong counters; raw no-print windows remain zero while zero-denominator normalised trade
  imbalance is missing and scored on its own support; empty M5 depth bands are missing and enforce
  the primary common case. All retained bands are populated, so primary support/results do not
  change. The corrected M2b h1=5 s/h2=5 s arm adds +3.639 pp pooled on 306 test anchors but is
  +6.094/-0.762 pp by tape and fails all-three dependence resolution (1.48/1.83/1.64).
- Added deterministic seven-band contribution/stability records for M4/M5. At the reproducing M4
  h1=2 s/h2=5 s cell, levels 11-20 have the largest mean-absolute held-out contribution (1.681
  ticks); band signs are stable for 1, 11-20, 51-100 and 101-200 only. Added and hashed the missing
  ablation, intensity, support and gate CSVs alongside ranking; all eight machine artifacts replay
  byte-for-byte. The 28-row frozen-spec audit is
  `docs/OFI-HORSERACE-SPEC-COVERAGE-2026-08-19.md`.

### `X-CKS-L1-OFI-DAT20-04` — Cont-Kukanov-Stoikov level-one OFI versus future returns, depth-controlled

- Added the canonical CKS best-quote event increment
  `e = 1{P^B_n >= P^B_{n-1}} q^B_n - 1{P^B_n <= P^B_{n-1}} q^B_{n-1} - 1{P^A_n <= P^A_{n-1}} q^A_n
  + 1{P^A_n >= P^A_{n-1}} q^A_{n-1}` in `src/shaurya/signals/cks_l1_ofi.py`, with an eight-component
  auditable decomposition (price improvement, same-price displayed addition, same-price displayed
  removal, price worsening, on each side) that is asserted to reconstruct the increment exactly.
- Frozen 25-cell grid: 5 accumulation windows (0.5-10 s) x 5 return horizons (1-30 s), 0.5 s causal
  gap, same publication clock, completeness rule, 70/30 within-tape split and 120 s embargo as
  `X-OFI-DAT20-03`. Six models per cell plus a comparison arm carrying that scan's price-keyed
  top-10 construction against the identical depth control.
- **Amendment 1 (`docs/CKS-L1-OFI-SPEC-AMENDMENT-1-2026-08-19.md`), pre-report and outcome-blind but
  not pre-artifact, corrects the response-horizon scope**: `h2 = 0.5 s` is admitted after measuring
  that the depth20 response clock is a hard 500.7 ms metronome whose two as-of endpoints resolve to
  different snapshots in 99.4-99.5% of cases. The core response family is 0.5/1/2/5/10 s and the
  30 s horizon is retained as a separately labelled longer robustness arm, taking the grid from 25
  to 30 cells. The frozen specification is **not** rewritten; the amendment is additive and
  separately timestamped. `h1` keeps its 0.5 s floor on restated grounds — depth200 publishes every
  ~200 ms, but best-quote changes arrive only 1.42/s and 0.77/s, so below half a second the
  regressor is zero in a majority of windows and degenerates into a near-binary indicator. No 0.1 s
  or 0.25 s arm was constructed or claimed.
- Admitting the shorter horizon lets six end-of-tape observations qualify that previously had no
  covered future horizon, moving the sample from 5,204 to **5,210** (3,646 train, 960 embargoed,
  604 test). All 30 cells were recomputed on the amended sample; no figure in the report is carried
  over from the 25-cell run.
- Depth control is measured at or before the OFI window end (`log1p` of best-bid + best-ask
  displayed size); depth scaling divides OFI by the causal average level-one depth with a
  one-contract floor. `assert_no_lookahead` and a test enforce that no window starts after its own
  observation or reaches back beyond its own length. Zero observations hit the scaling floor.
- **Identification held explicit:** Dhan publishes snapshots, so gross limit arrivals and gross
  cancellations are unidentified. Same-price changes are labelled displayed additions and displayed
  removals throughout. The coalesced trade fields (310 packets, 52,715 identified executed
  contracts) exceed level-one same-price displayed removals (29,120 contracts), so no clean
  execution-versus-cancellation split is identified and the artifact records a saturated upper
  bound rather than a fabricated share.
- **Result (amended 30-cell grid):** raw level-one OFI adds at most +1.44 pp of held-out R² over the
  depth control (1 s -> 2 s) and is positive in 16 of 30 cells; depth scaling helps in 27 of 30 cells
  with a best increment of +6.00 pp (2 s -> 2 s, pressure-only OOS R² 6.30%, +0.84 ticks per unit
  pressure, +1.70 ticks per training SD). Only 1 of 30 raw and 0 of 30 pressure cells clear
  Newey-West, block bootstrap and non-overlapping blocks together; that single survivor flips
  coefficient sign across the two tapes (+1.72 vs -0.32 ticks per training SD) and its entire
  increment comes from the first tape. The best pressure cell scores higher out of sample than in
  sample (5.30% vs 1.36%). The amended h2 = 0.5 s arm is a clean negative: no cell clears the checks
  and the past-return mirror beats the future increment in all five of its cells, because over
  0.5 s the futures mid is unchanged in 59.8% and 78.0% of observations on the two tapes.
- **Comparison:** `X-OFI-DAT20-03`'s lead survives an independent depth control at +7.12 pp
  incremental (8.38% OOS R²) while level-one OFI contributes -0.55 pp at that cell with a negative
  coefficient — confirming that lead is a levels-2-10 phenomenon, not a best-quote one.
- Measured object characteristics: 5,470 valid transitions over 1,305 s (4.19/s); best-quote price
  moves carry 80.9% of absolute contribution and same-price displayed size changes only 19.1%;
  81.4% of contribution is ask-side; median best-bid/best-ask spread is 100 and 134 ticks on the two
  tapes, so level one here is a lone quote at the front of a wide gap rather than a contested queue.
- Added 33 tests in `tests/test_cks_l1_ofi.py`, the `scripts/cks_l1_ofi_scan.py` CLI, the frozen
  specification `docs/CKS-L1-OFI-SPEC-2026-08-19.md`, its Amendment 1, the plain-English report
  `docs/CKS-L1-OFI-2026-08-19.md`, and the primary-literature benchmark
  `docs/research/OFI-LITERATURE-BENCHMARK-2026-08-19.md` separating signed trade imbalance, VPIN,
  exact CKS L1 OFI, static queue imbalance and multi-level OFI. Deterministic replay reproduces the
  grid and component artifacts byte for byte, and the scan JSON byte for byte except for its
  embedded `protocol.code_commit` field. Exploratory observation only; `confirmatory_eligible: false`; not part of `H-SIG21`.
- Hardened the Amendment 1 horizon coverage: the 0.5 s response horizon is now exercised **end to
  end on its measured value**, not only by membership in `CKS_RETURN_HORIZONS_SECONDS`. On a
  synthetic tape whose mid advances exactly one futures tick per 0.5 s publication, each horizon's
  future target and past mirror must equal `2 x horizon` ticks, and the 0.5 s target is asserted not
  to alias the 1 s one; a second test asserts all five 0.5 s cells are fitted and bootstrapped. Both
  guard the sub-second conversion `int(horizon * NANOSECONDS_PER_SECOND)` and the integer
  block-bootstrap seed `int(horizon * 10_000)`, and both were mutation-checked against the
  truncating and float-seed variants. Re-running the scan reproduces both commit-independent
  artifacts byte for byte, so no reported figure changes.

### `X-OFI-DAT20-03` — price-keyed OFI versus future returns

- Added a frozen exploratory grid over five OFI accumulation windows (0.5–10 s), seven cumulative
  depths (1–200) and five future-return horizons (1–30 s), with a 0.5 s causal gap and chronological
  per-tape train/test separation.
- Price-keyed OFI follows quantity at absolute prices across consecutive depth200 snapshots, assigns
  each price to the shallowest endpoint rank, excludes vendor-window boundary churn, and aggregates
  both cumulative depths and disjoint nested bands.
- The strongest lead is 10 s OFI through level 10 → next 10 s depth20-mid return: state+OFI OOS R²
  7.78%, incremental +7.91 pp, positive on both tapes. Levels 2–10 account for the gain; deeper
  bands do not.
- The lead is not dependence-robust (Newey-West 1.51, stationary bootstrap 1.65, non-overlapping
  blocks 1.20), and the past-mirror gain is larger (+13.29 pp). It is therefore an exploratory
  candidate to freeze and retest, not a confirmed predictive signal.
- Added tape-stratified diagnostics, same-window and past-mirror arms, a complete 175-cell JSONL
  grid, nested-depth results, boundary accounting, regression tests, and the plain-English report
  `docs/OFI-PREDICTIVE-SCAN-2026-08-19.md`.

### D34 / `H-SIG21-A1` — the primary episode window is bound to each cell's own `Z + h2`

- **`docs/sig-claims/H-SIG21.md` is unchanged.** The registration body is immutable and its single
  commit `f2cf650` is the registration clock required by `D29`/`SIG-19`; editing it in place would
  make the file and the clock disagree. The change is recorded as `docs/sig-claims/H-SIG21-A1.md`,
  a dated numbered amendment listed in the `docs/sig-claims/README.md` companion index.
- **Pre-data, not post-hoc.** Committed and pushed before any confirmatory tape exists — zero of
  the 25 required post-registration sessions (5 calibration + 20 evaluation) have been collected.
- Approved by Aryan by voice 2026-08-19 ~17:40 IST. This is option (iii) of the §14 change-control
  proposal in `docs/SIG-21-EXPLORATORY-RESPONSE-2026-08-19.md` §9; options (i), (ii) and (iv) are
  recorded as considered and rejected, with reasons, in the amendment.
- Added `episode_window_ns(gap_seconds=..., horizon_seconds=...)` to
  `src/shaurya/signals/deep_book_response.py`, plus `FAMILY_MAXIMUM_EPISODE_WINDOW_NS` /
  `..._SECONDS` so the old convention has an explicit name rather than being the unmarked default.
- `build_cell_series` now forms the primary risk set under each cell's own window. Measured effect
  at the registered 99.5% threshold: a `Z=0.5 s, h2=1 s` cell retains 260 non-overlapping episodes
  under its own 1.5 s window against 2 under the 11 s family maximum — a factor of 130.
- **The family-maximum path is kept, not deleted.** `build_response_family` now emits a fourth arm
  `robustness_family_maximum_episodes` for all 384 cells, which reproduces the pre-amendment primary
  arm exactly. It is never promoted to primary. Every family artifact carries
  `episode_window_convention: "per_cell_z_plus_h2"`, `episode_window_amendment: "H-SIG21-A1"` and a
  per-cell `episode_window_seconds`.
- Estimand, estimator, HAC lag floor, the 384-cell family, thresholds, strata, negative controls
  and power gates are all unchanged. Cross-horizon `N` comparisons stop being meaningful; that cost
  is stated in the amendment rather than hidden.
- **The matched-quiet-control definition is deliberately unchanged** and remains an open item.
  Aryan deferred it: *"only tomorrow's limit order book activity will tell us what is a quiet
  moment."* No replacement is proposed. `H-SIG21` §6's 11-second quiet window stands.
- `select_primary_non_overlapping_episodes` was re-examined under the per-cell window and left
  unchanged — it remains the identity on `cluster_event_episodes` output at every window size. Its
  docstring now states that its zero exclusion count is a construction property and must never be
  cited as evidence, and it records why the function is retained: it is not the identity on episode
  sets assembled from more than one clustering call, which per-cell windows make more likely.

### `X-DEEPBOOK-DAT20-02` — what ordinary deep-book activity says about the futures price

- Added `scripts/deepbook_normal_activity_scan.py` and
  `src/shaurya/signals/deep_book_normal_activity.py`. **Anomalies are dropped entirely**: no
  thresholds, no rare-tail selection, no episodes, no anomaly detector. Ordinary state and flow of
  the 200-level book at every depth200 publication, against the depth20 mid-price.
- **This is not `H-SIG21`.** It shares two source tapes and the mid-price target convention and
  nothing else. Every artifact carries `is_part_of_h_sig21: false` and `confirmatory_eligible:
  false`. Refusals in code: a confirmatory or economic framing is rejected before a file is opened,
  any tape outside the two pinned pre-registration SHA-256s is rejected, and a filtered or
  truncated table is rejected.
- 584 features per publication: quantity, order-count and average-order-size imbalance plus region
  totals and per-region book shape, over five level-index regions (best / top 5 / top 20 / 21-50 /
  51-200) **and** four price-distance regions (≤₹5 / ₹5-20 / ₹20-50 / >₹50), each differenced at
  tick, 1 s and 5 s look-backs resolved as-of. Average order size is labelled a **proxy**
  throughout: the feed carries no order IDs, so per-order identity and lifetime are unidentified.
- Target: depth20 BBO mid-price return in futures ticks at 1, 5, 10, 30 and 60 s, last observation
  at or before each endpoint, endpoints past coverage refused rather than resolved backwards.
  Future, past-mirror and contemporaneous legs are carried separately and never merged.
- **Central test — the nested region comparison.** best quote only → top 5 → top 20 → add 21-50 →
  add 51-200, fitted with regularised linear models on a chronological 70% split with a 120 s
  embargo band discarded from both sides, penalty selected on a held-out tail of the training set
  only. **On this tape the region beyond level 20 adds nothing: 0 of 10 deep steps in the
  level-index ladder are distinguishable from zero and half are negative.** One of ten deep steps
  in the price-distance ladder fires, on four non-overlapping blocks, and is not believed.
- A step counts as distinguishable only when a Newey-West statistic, a within-tape stationary block
  bootstrap and a non-overlapping block estimate all agree in sign and all exceed 1.96. The naive
  standard error is emitted alongside with `naive_inference_valid: false`.
- **The past-return placebo fires 8 times out of 20 against a real 2 out of 20**; the univariate
  tables agree (past 32.2%, future 29.3%, contemporaneous 39.1%, against a 5% null). The apparatus
  predicts the past about four times as often as the future, so the raw arms are measuring drift.
  Raw scoring inflates the 60-second out-of-sample number from 0.05 to 0.40 purely from the fall.
- A gradient-boosted stump ensemble is included as a **yardstick only** (`D11(c)` / `SIG-18`
  logic), labelled never a strategy candidate. It ties the linear fits and is worse at two of five
  horizons, so the near-nothing is not the linear form being too restrictive.
- Required-sample figures are emitted per step: one full trading session settles the 1 s and 10 s
  questions; 60 s needs 48-107 sessions.
- Four defects found by running it, three of them checks that could not have failed whatever the
  data said, all fixed with regression tests: the raw and drift-adjusted columns collapsed onto
  each other after adjustment; the contemporaneous leg was identically 0.0 because both ends
  resolved to the same publication; the side-label control mirrored the whole sample, which a
  refit linear model relearns exactly; and the ridge penalty selected the largest value in its grid
  in every fit, a censored search rather than a choice.
- Report: `docs/DEEPBOOK-NORMAL-ACTIVITY-2026-08-19.md`. **Nothing in it is a result and nothing
  predictive or economic is claimed:** 22 minutes, one contract, one mid-afternoon half-hour, one
  price direction, zero between-session variation.

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
