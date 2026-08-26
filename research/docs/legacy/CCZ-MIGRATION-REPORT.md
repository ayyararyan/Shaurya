# CCZ OFI migration — completion report

**Specification:** `docs/CCZ-OFI-MIGRATION-SPEC-2026-08-20.md` (`D37 / CCZ-OFI-MIGRATION-2026-08-20`)
**Branch:** `ccz-ofi-migration` in `/Users/maheit/Documents/Shaurya-ccz`, based at `be2dd99`
**Commit range:** `7cda269..HEAD` (three implementation commits after the frozen spec)
**Status vocabulary:** §12 of the working contract. Nothing below is Level 4 (live verified).

---

## Owner summary

Cont–Cucuringu–Zhang is now the only definition of order flow imbalance in this repository.
Everything that used to compute a different object either computes CCZ or has been removed.

Two constructions were removed because they are not CCZ:

1. `deep_book_ofi.price_keyed_ofi_transition` accumulated signed innovations into a **running sum
   across levels** and applied no depth scaling. CCZ never cumulate. The whole `X-OFI-DAT20-03`
   scan was built on it, so the scan and its driver script went with it. The module now holds only
   the transition-validity, control and mid-return helpers the surviving scans share.
2. `ofi_horserace` M5 divided each disjoint band by **that band's own** mean depth. CCZ Eq. (3)
   divides every level by **one common** `Q^{M,h}` precisely so relative cross-level magnitudes
   survive. The bands are gone; levels enter individually.

The level-one CKS (2014) increment is CCZ Eq. (1)'s base case and was left byte-unchanged, as
instructed. Only the comparison feature it carried alongside — which pointed at the retired
price-keyed top-10 sum — moved, to the CCZ ten-level simple average.

**Interpretation change:** yes, and it is not small. Pre-migration and post-migration numbers are
not comparable and must never be pooled without an explicit estimator column. Every artifact now
carries an `estimator: "CCZ"` block stating that.

**Action needed from Aryan:** two decisions, both stated in "Contradictions found" below — the
retired pre-named replication lead, and whether the removed `scalar_ofi` controller stage should
stay removed.

**Bottom line:** the frozen specification is fully implemented and tested. It is not live
verified, and it has not been run against any real tape.

---

## Specification coverage

Required: 16 non-test requirements · Implemented: 16 · Partial: 0 · Missing: 0 · Blocked: 0
Acceptance tests: 8 of 8 passing. Coverage: **100%**.
Overall status: **IMPLEMENTED AND TESTED; LIVE VERIFICATION PENDING.**

The full per-requirement matrix with code locations and test names is
`docs/CCZ-OFI-MIGRATION-TRACEABILITY-2026-08-20.md`. Summary:

| ID | Status | Where |
|---|---|---|
| `EST-CCZ-01` per-level order flow (Eq. 2 terms) | Implemented, Tested | `ccz_ofi.py:ccz_level_flow` |
| `EST-CCZ-02` level-`m` OFI, no sum over levels | Implemented, Tested | `ccz_ofi.py:CczFlowSeries.window` |
| `EST-CCZ-03` one common `Q^{M,h}` (Eq. 3) | Implemented, Tested | `ccz_ofi.py:CczFlowSeries.window` |
| `EST-CCZ-04` integrated OFI, train-only PC1 (Eq. 4) | Implemented, Tested | `ccz_ofi.py:fit_integrated_weights` |
| `EST-CCZ-05` four declared aggregation arms | Implemented, Tested | `ofi_horserace.py:evaluate_ccz_aggregation_arms` |
| `EST-CCZ-06` `M=10` primary, `{1,5,20,200}` robustness | Implemented, Tested | `ccz_ofi.py:DECLARED_LEVEL_COUNTS` |
| `CCZ-IMPL-01` new module | Implemented, Tested | `src/shaurya/signals/ccz_ofi.py` |
| `CCZ-IMPL-02` remove cumulative construction | Implemented, Tested | `deep_book_ofi.py` |
| `CCZ-IMPL-03` remove per-band normalisation | Implemented, Tested | `ofi_horserace.py` |
| `CCZ-IMPL-04` rebuild horse-race families | Implemented, Tested | `ofi_horserace.py` |
| `CCZ-IMPL-05` retain level-1 CKS unchanged | Implemented, Tested | `cks_l1_ofi.py` |
| `CCZ-IMPL-06` dashboard consumes CCZ | Implemented, Tested | `analytics/ofi_dashboard.py` |
| `CCZ-IMPL-07` replication / live-partial drivers | Implemented, Tested | `data/ofi_replication.py`, `data/ofi_live_partial.py` |
| `CCZ-IMPL-08` per-unit commit-pin re-check | Implemented, Tested | `scripts/ofi_full_session_controller.py` |
| `ID-CCZ-01` snapshot relabelling documented | Implemented, Tested | `ccz_ofi.py:ID_CCZ_01_LIMITATION` |
| `OPS-CCZ-01` pin re-check, fail closed, per-stage HEAD | Implemented, Tested | `scripts/ofi_full_session_controller.py` |

---

## Verification, verbatim

Run from `/Users/maheit/Documents/Shaurya-ccz` with `.venv/bin/python` (Python 3.14).

```
$ .venv/bin/python -m pytest -q
576 passed, 9 warnings in 59.68s
```

Baseline at `be2dd99` was 549 passed. Net `+27`: 18 new tests in `tests/test_ccz_ofi.py`,
8 new tests across the horse-race, dashboard and replication suites, and `tests/test_deep_book_ofi.py`
rewritten from 5 tests of the retired construction to 8 tests of the retained primitives.
The 9 warnings are the pre-existing `RuntimeWarning: invalid value encountered in divide` from
`deep_book_normal_activity.py:871`, unchanged in nature by this work.

```
$ .venv/bin/python -m ruff check .
All checks passed!
```

```
$ .venv/bin/python -m mypy src
Success: no issues found in 60 source files
```

```
$ .venv/bin/python -m ruff format --check .
47 files would be reformatted, 134 files already formatted
```

**`ruff format --check` is not clean, and it was not clean before this work either.** The
baseline at `be2dd99` reports `47 files would be reformatted, 133 files already formatted`.
The count of unformatted files is identical; the extra formatted file is the new `ccz_ofi.py`.
I checked each file I touched against the baseline: every one that `ruff format` now flags was
already flagged at `be2dd99`. I introduced no new formatting violations and deliberately did not
reformat 47 unrelated files, which would have buried the migration diff. `ruff check` — the gate
the project actually enforces — is clean.

---

## What changed, per file

### New

- **`src/shaurya/signals/ccz_ofi.py`** — the estimator. `ccz_level_flow` is the reference scalar
  Eq. (2) implementation; `CczFlowSeries` is the vectorised prefix structure that answers window
  queries; `CczWindow` carries raw `OFI^{m,h}`, the single `Q^{M,h}`, and `ofi^{m,h}`;
  `fit_integrated_weights` / `IntegratedWeights` implement Eq. (4) with a train-only PC1, a
  recorded sign fix and a reported explained-variance ratio; `aggregate_window` gives the
  `EST-CCZ-05` scalar arms; `ccz_metadata` is the estimator block every artifact must carry.
  `CczFeatureSchema` / `CczFeatureVector` are a dense `Mapping[str, float]` — see "Engineering
  choices" below.
- **`tests/test_ccz_ofi.py`** — `VAL-CCZ-01` to `VAL-CCZ-08`, 18 tests.
- **`docs/CCZ-OFI-MIGRATION-TRACEABILITY-2026-08-20.md`** — the requirements matrix.

### Changed

- **`src/shaurya/signals/deep_book_ofi.py`** — reduced from 895 lines to 84. Removed:
  `PriceKeyedOFITransition`, `price_keyed_ofi_transition`, `_price_map`, `_boundary_churn`,
  `DEPTH_CUTOFFS`, `ofi_feature`, `band_feature`, `OFIObservation`, `build_ofi_observations`,
  `evaluate_grid`, `evaluate_nested_depth`, `evaluate_same_window`, `build_ofi_artifact` and the
  scoring/inference helpers that served only them. Retained: `_invalid_transition`, `_controls`,
  `_mid_return`, `_label`, `OFI_WINDOWS_SECONDS`, `CAUSAL_GAP_SECONDS`, `FUTURES_TICK_SIZE`.
  The docstring records the retirement rather than hiding it.
- **`src/shaurya/signals/ofi_horserace.py`** — `M4` is now CCZ Eq. (2) per level (levels 1–10),
  `M5` is CCZ Eq. (3) per level under the one common denominator, `M6` combines them.
  `BANDS`, `pk_band_feature`, `adjusted_band_feature` and `_band_depths` are gone.
  `_band_contribution_diagnostics` became `_level_contribution_diagnostics`, reporting individual
  levels rather than cumulative bands. New `evaluate_ccz_aggregation_arms` evaluates all four
  `EST-CCZ-05` arms at all five `EST-CCZ-06` level counts, in both the future and past-mirror
  directions. New `ccz_feature_schema` declares the feature namespace once.
  Artifact `schema_version` 2 → 3, with a `ccz` block, `ccz_aggregation_arms_future`/`_past`, and
  the arm cell count added to `multiplicity`.
- **`src/shaurya/signals/cks_l1_ofi.py`** — `cks_l1_transition` untouched, which is the point of
  `CCZ-IMPL-05`. Its `comparison_feature` moved from the retired price-keyed top-10 sum to the CCZ
  ten-level simple average (a deterministic arm needing no fitted component, so it can be
  materialised at construction time without leaking anything). The artifact gained the `ccz` block.
- **`src/shaurya/signals/surface_futures_predictive.py`** — found in the §9 adjacent audit, not
  named in the spec's §3 table. It carried **both** defects: `pk_levels2_5_*` was a cross-level
  band from cumulative differences, and each band was divided by its own mean depth. Migrated to
  CCZ at `M = 5` (the Quote/Full tape's level count): `ccz_level{1..5}_raw` and
  `ccz_level{1..5}_depth_scaled`, one common `Q^{5,h}`. `H4_5L` and `H5_5L` are now Eq. (19)
  `PI^[5]`. Regressor count in those two families went from 2 to 5.
- **`src/shaurya/analytics/ofi_dashboard.py`** — consumes the CCZ families through the unchanged
  horse-race entry points. New `_integrated_arm_diagnostics` fits `w_1` on each block's training
  rows only and publishes the EVR, weights and applied sign. The payload, the cells payload and
  the closing artifact all carry the `ccz` block. **Cell geometry is unchanged** (`M0..M6 × 5
  windows × 5 horizons = 175`), so the dashboard's frozen multiplicity and Benjamini–Hochberg
  accounting are unaffected.
- **`src/shaurya/data/ofi_replication.py`, `ofi_live_partial.py`** — neither computes an
  estimator. The receipt and the partial claim now state which estimator downstream analysis used,
  so a post-migration artifact cannot be mistaken for a pre-migration one. Receipt
  `schema_version` `1.0.0` → `1.1.0`.
- **`scripts/ofi_full_session_controller.py`** — `OPS-CCZ-01`. New `assert_on_pin(unit)` re-checks
  HEAD, worktree cleanliness and origin ancestry, fails closed, and records the HEAD observed. It
  runs in `preflight`, before every analysis unit, and again after each unit completes, so outputs
  that straddle two revisions are caught. The hash manifest now carries
  `observed_code_commit_by_unit` alongside the command-line constant. The `scalar_ofi` stage was
  removed with its script.
- **`scripts/ofi_horserace.py`** — new `--ccz-arm-output` writer emitting one row per aggregation
  arm per level count per cell.

### Removed

- **`scripts/deepbook_ofi_scan.py`** — the driver of the retired `X-OFI-DAT20-03` scan. Its
  estimator no longer exists, so the script cannot run.

No artifact files were deleted. Pre-migration outputs under any run directory are untouched.

---

## What the dashboard now consumes

`ANL-06` (`X-OFI-DASHBOARD-2026-08-20`) reads the same tape through the same
`build_horserace_observations` entry point, so the cell grid, ratchet, embargo and honesty rails
are unchanged. What changed is the content of the order-flow columns:

| Cell | Before | Now |
|---|---|---|
| `M0` | depth + spread baseline | unchanged |
| `M1` | static L1 queue imbalance | unchanged |
| `M2` | signed trade imbalance | unchanged |
| `M3` | CKS L1 event increment | unchanged — this is CCZ Eq. (1) |
| `M4` | seven price-keyed cumulative bands | ten CCZ per-level `OFI^{m,h}` (Eq. 2) |
| `M5` | seven bands, each over its own mean depth | ten CCZ `ofi^{m,h}` over one common `Q^{10,h}` (Eq. 3) |
| `M6` | all of the above | as above, with the CCZ blocks |

Additionally published, per refit: `ccz` (estimator name, reference, equations, level counts,
aggregation arms, denominator floor and floor-event count, EVR by window, and the `ID-CCZ-01`
limitation verbatim) and `ccz_integrated_weights` (per window: status, `w_1`, `w_1/‖w_1‖_1`, L1
norm, EVR, applied sign, dominant level, training rows, and `fitted_on: "training_rows_only"`).

The Eq. (4) integrated arm is **not** a dashboard leaderboard cell. Adding it would have changed
the frozen cell count and therefore the multiplicity accounting; it is published as a diagnostic,
and it is ranked as a competing arm in the batch horse race instead.

---

## Contradictions found between the spec and the codebase

Two, both surfaced rather than silently resolved.

### 1. A pre-named replication lead is defined on the retired estimator

`R-OFI-FULLSESSION-2026-08-20` registered two leads before its tape existed. The first,
`scalar_top10_10s_to_10s` — "top-10 price-keyed OFI, 10 s accumulation to next 10 s return" — is
defined on exactly the construction `CCZ-IMPL-02` removes. It cannot be computed after the
migration.

I did **not** re-point it at a CCZ quantity. That would change a pre-registered estimand, which
§17.2 puts on Aryan's side of the line, not mine. `build_fixed_lead_summary` now emits it as
`status: "estimator_retired"` with `incremental_oos_r2: null`, the prior value `0.0791` for the
record, and the reason. `FIXED-LEADS.md` says so in words and reports no substitute number. The
second lead, depth-normalised CKS `M3b` at 2 s → 2 s, is unaffected and still reported in full.

**Decision needed from Aryan:** leave this lead retired, or approve a named CCZ successor lead
(the natural candidate is the `M = 10` integrated arm at `h1 = 10 s`, `h2 = 10 s`) — as a *new*
registration, not a redefinition of the old one.

### 2. The spec says "remove" for `deep_book_ofi` but the scan had a live pipeline stage

§3 assigns `CCZ-IMPL-04` "rebuild" only to `ofi_horserace.py`; for `deep_book_ofi.py` it says
"remove". Taken literally — which is how I took it — the `X-OFI-DAT20-03` scan ends, and with it
`scripts/deepbook_ofi_scan.py` and the controller's `scalar_ofi` stage. The information is not
lost: `evaluate_ccz_aggregation_arms` sweeps `M ∈ {1, 5, 10, 20, 200}`, which is deeper coverage
than the retired depth-cutoff sweep, and it does so with a correct estimator.

**Decision needed from Aryan:** confirm the stage stays removed. If you want a standalone CCZ
level-count sweep as its own pipeline stage rather than a section of the horse-race artifact, say
so — I kept it in one place deliberately, so the same object is not counted twice in the
multiplicity accounting.

### 3. A smaller one, for the record

The spec's `VAL-CCZ-05` says the `‖w_1‖_1` normalisation "makes the integrated weights sum to 1".
That holds exactly when all loadings share a sign; in general it is the **L1** norm that is one.
The test asserts the L1 norm is exactly one always, and additionally asserts the plain sum is one
when the signs agree (which the sign fix makes the normal case). No behaviour was changed.

---

## Engineering choices worth flagging

**Dense feature vectors.** `EST-CCZ-06` declares `M = 200`. With five windows that is one thousand
per-level names per anchor. A plain per-anchor `dict` of ~1,100 float entries costs roughly 60 kB,
which at twenty thousand anchors is over a gigabyte in the live dashboard — the dashboard keeps
every anchor and rebuilds observations on each refit. `CczFeatureVector` is a `Mapping[str, float]`
backed by one dense array plus a presence mask against a shared interned schema, at ~9 kB per
anchor. The mapping interface is identical, so `name in features` and `features[name]` are
unchanged everywhere, and absence stays explicit rather than becoming a zero.

**Availability, not zero-filling.** A window supports level count `M` only if *every* event in it
carried `M` levels on both sides. Otherwise that `M`'s window is unavailable, the feature is
absent, and the arm is reported `data_insufficient_level_support`. Raw levels are materialised
only up to the deepest supported declared `M`, so a hundred-level book yields levels 1–20 and no
more. Nothing is silently zero-filled.

**Denominator floor.** `Q^{M,h}` is floored at 1.0 contract, as the spec requires, and every
flooring event is counted into `ccz_depth_denominator_floored` and surfaced in the artifact's
`ccz` block rather than absorbed.

---

## Residual risks

1. **`ID-CCZ-01` is real and now active.** Rank-keyed comparison under snapshot data means one
   best-quote move relabels every level, so a single price change can register as flow at many
   levels at once. This was Aryan's explicit decision (b) — document, do not patch. It is carried
   verbatim in every artifact. It will inflate apparent multi-level activity, and the deeper the
   level, the worse it gets. The `M = 200` arm is the most exposed.
2. **No real-data run.** Every number in this report comes from synthetic fixtures. The estimator
   has never seen a Dhan tape. Behaviour on real books — how often the `M = 200` support condition
   actually holds, how often the denominator floors, how much of the variance PC1 explains — is
   unknown.
3. **Runtime and memory on a full session are unmeasured.** From the immutable 09:45 snapshot the
   depth200 rate is about 730 publications per minute, so a full session is roughly 190,000
   transitions. The prefix arrays at `M = 200` are about 300 MB per tape per array, which is small
   next to the `BookState` objects already held, but the aggregation-arm sweep adds 25 ridge fits
   of a 200-regressor design per direction and has not been timed on that scale.
4. **`PI^[200]` is statistically thin.** Two hundred regressors against a few hundred training
   anchors is a wide problem even with the inner-CV ridge. The existing minimum-observation and
   degrees-of-freedom guards will mark cells insufficient rather than fit nonsense, but the arm's
   estimates should be read with that in mind. `X-DEEPBOOK-DAT20-02` already found no incremental
   gain beyond level 20.
5. **`OPS-CCZ-01` is fixed in this clone only.** The live controller at
   `overnight-runs/ofi-partial-live-20260820/code/controller.py:406` still checks the pin once, in
   `preflight`. It is outside this write scope and running right now; I did not touch it.
6. **Reruns of old artifacts will not reproduce.** Anything regenerated after this branch merges
   will differ from the pre-migration numbers by construction. That is the intended effect, but it
   means the 11:30 and 13:30 checkpoint outputs and the migrated code are not comparable.

---

## Explicitly not done

- **Not live verified.** Nothing here ran against a real tape. Evidence level is 2 (Tested) for
  every requirement, with `VAL-CCZ-08` additionally at level 3 (dry-run verified: the acceptance
  test builds a complete horse-race artifact from a synthetic tape and writes all nine artifact
  files, checking each is non-empty and well formed).
- **No analysis was run against `/Users/maheit/Documents/Shaurya/data/live-captures/`.** As
  instructed. The immutable snapshots were read once, read-only, only to count depth200 rows for
  the memory estimate in "Residual risks".
- **The live repository at `/Users/maheit/Documents/Shaurya` was not touched.** No writes, no
  commits, no checkouts. No tmux session or process was signalled.
- **Nothing was pushed.** Three commits exist locally on `ccz-ofi-migration` only.
- **Pre-migration artifacts were not relabelled in place.** §6 of the spec requires they be
  preserved and relabelled; they are preserved and untouched. The relabelling exists as a
  statement in the code and in this report, not as an edit to already-written artifact files —
  editing produced artifacts after the fact would itself be a provenance problem. If Aryan wants
  a sidecar `estimator: "pre-CCZ"` marker written next to the existing outputs, that is a small
  follow-up and I did not assume it.
- **The retired `X-OFI-DAT20-03` numbers were not recomputed under CCZ.** The spec relabels them;
  it does not ask for a re-run.
- **`ruff format` was not applied repository-wide.** 47 files were already unformatted at
  `be2dd99` and remain so; see the verification section.
