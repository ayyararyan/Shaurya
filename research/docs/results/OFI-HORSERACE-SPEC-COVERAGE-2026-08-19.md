# Frozen-specification coverage audit — `X-OFI-HORSERACE-DAT20-05`

**Audited specification:** `docs/OFI-HORSERACE-SPEC-2026-08-19.md`

**Execution commit:** `c18a4bd959ea6e882625a37c57d75211969f06dc`

**Audit trigger:** post-completion review found material FLOW/ROB/OUT gaps

**Evidence boundary:** Level-3 replay machinery; empirical content remains exploratory and
`confirmatory_eligible=false`.

## Corrected completion claim

The earlier completion claim was too broad. Exact trade-classifier/alignment versions were not
enforced; zero-denominator normalised trade imbalance was fabricated as zero; empty M5 bands were
floored instead of marked missing; per-band contribution stability and four promised CSVs were
absent. The global audit also found that declared normalised sub-arms lacked the frozen
dependence-aware error comparison. All were repaired and regression-tested before this audit was
closed.

## Requirement traceability

| ID | Frozen requirement | Status | Code / test / output evidence |
|---|---|---|---|
| DATA-01 | Only the two pinned DAT-20 tapes | Implemented | `scripts/ofi_horserace.py::build_tape_input`; permitted-tape/hash guards; artifact `tapes` |
| DATA-02 | h1/h2 0.5/1/2/5/10; 30 gated | Implemented | module constants; 175 future and 175 past primary cells; zero conditional cells |
| DATA-03 | Z=0.5 causal future midpoint return | Implemented | `build_horserace_observations`; no-lookahead test |
| DATA-04 | Existing quality/epoch filters, 70/30 split, 120 s embargo | Implemented | canonical builders/splitter; split and support tests |
| DATA-05 | Cell-level common complete case plus model-specific loss | Implemented | `_has_features`, `evaluate_cells`, 450-row support table; empty-band common-case test |
| DATA-06 | Training-only fitting and transformations | Implemented | `_fit_score`, `select_ridge_alpha`; test-set perturbation regression |
| STATE-01 | M0 log L1 depth plus spread only | Implemented | `model_features`; exact model-label test |
| STATE-02 | Terminal L1 queue imbalance; zero denominator missing | Implemented | construction rejects unusable zero-depth anchors; M1 nesting test |
| FLOW-01 | Exact versioned signed trades; coalesced/degraded excluded; ratio only for positive volume | Implemented | canonical DAT constants in `build_trade_series`; four version-exclusion counters; raw/ratio tests |
| FLOW-02 | Canonical CKS L1 event flow plus labelled depth scaling | Implemented | imported `cks_l1_transition`; sibling-reuse/sign test |
| FLOW-03 | Seven-band Ridge OFI with coefficients, collinearity and contribution stability | Implemented | M4 fit plus `_band_contribution_diagnostics`; seven-band output test |
| FLOW-04 | Causal band-depth adjustment; floor one; empty band missing | Implemented | band-presence prefix and common-case filter; truncated-book regression |
| EST-01 | Regularised M6 plus leave-family-out ablations | Implemented | M6 feature map; 125 ablations; ablation CSV |
| EST-02 | Complete fit, error, coefficient, support and standardisation fields | Implemented | `evaluate_cells`, normalised sub-arm metrics, per-band diagnostics, support CSV |
| EST-03 | Pooled fit with pooled target mean; per-tape scores/directions | Implemented | `_fit_score`, `_per_tape_scores`, `_direction_by_tape` |
| OOS-01 | Complete output; rankings only pointers | Implemented | complete JSONL cells plus 150-row ranking CSV |
| OOS-02 | Rank future increment; retain tape/sign diagnostics and negatives | Implemented | `compact_rankings`; complete cells retain negative values |
| ROB-01 | HAC, stationary bootstrap and non-overlap checks | Implemented | `_inference` on primary and normalised sub-arms; iid explicitly invalid |
| ROB-02 | Full past mirror | Implemented | 175 primary plus 50 normalised past cells |
| ROB-03 | Same-window diagnostic separated | Implemented | 35 labelled diagnostic cells; cannot open gate |
| ROB-04 | Collinearity, band stability and attrition | Implemented | cell collinearity; 700 per-band records across future/past; support table |
| GATE-01 | Frozen four-condition 30 s gate | Implemented | five-candidate gate CSV; gate failed; zero 30 s cells |
| GATE-02 | Same-window and M6 cannot open gate | Implemented | explicit gate flags and gate regression |
| OUT-01 | JSON/JSONL plus ranking, ablation, intensity, support and gate CSVs; hashes/CLI | Implemented | eight byte-replayed machine artifacts and committed SHA-256 manifest |
| OUT-02 | Plain-English report with complete interpretation boundary | Implemented | `docs/OFI-HORSERACE-2026-08-19.md` |
| VAL-01 | Predictor, missingness, causality, fit, gate, determinism tests | Implemented | focused `tests/test_ofi_horserace.py`, including five new gap regressions |
| VAL-02 | Test/static/replay/diff/secret acceptance | Implemented | final verification record below |
| VAL-03 | TASKS/CHANGELOG update; H-SIG21 immutable | Implemented | current-state entries updated; H-SIG21 absent from diff |

## Artifact contract acceptance

| Artifact | Required rows | Semantic check | Status |
|---|---:|---|---|
| Main JSON | 1 object | schema 2; complete nested diagnostics; execution commit pinned | Passed |
| Future JSONL | 175 | 7 models x 5 h1 x 5 h2; blocked rows retained if applicable | Passed |
| Past JSONL | 175 | identical primary family/grid | Passed |
| Ranking CSV | 150 + header | 6 non-baseline models x 25 cells; not a filtered winner list | Passed |
| Ablation CSV | 125 + header | 5 omitted families x 25 cells | Passed |
| Intensity CSV | 95 + header | support and missingness carried per feature/window | Passed |
| Support CSV | 450 + header | future/past primary and normalised sub-arm support | Passed |
| Gate CSV | 5 + header | every non-combined candidate and all four conditions | Passed |

The retained tapes have all seven depth bands populated, so the corrected M5 empty-band rule causes
zero actual primary support loss; the synthetic truncated-book test proves it fails closed when a
band is absent. All 310 trade-schema packets have the exact canonical classifier and alignment
versions, so version filtering also changes no primary tape row. The normalised trade arm does
change: it now uses only anchors with positive qualified buy+sell volume and reports its own support.

## Final verification record

- Focused horse-race tests: **17 passed**.
- Full Python suite: **467 passed** with six known non-failing Ridge SVD warnings on deliberately
  collinear synthetic fixtures.
- Repository-wide Ruff: passed. Strict mypy: **52 source files passed**.
- `compileall`, JSON/schema checks, artifact-hash cross-check and `git diff --check`: passed.
- Authoritative 400-replicate run and a second run produced all eight artifacts byte-for-byte.
- Staged secret scan: passed. `docs/sig-claims/H-SIG21.md` was not touched.

## Audit result

Required components: **28** · Implemented: **28** · Partial: **0** · Missing: **0** · Blocked:
**0** · Unidentified by design: **0** (M2 is identified on these tapes). Required machine outputs:
**8/8**. Unapproved scope reductions: **0**. Unapproved proxy substitutions: **0**. Causal/leakage
audit: **passed**. Deterministic replay: **eight of eight files byte-identical**.

**Overall status:** complete at Level 3 for the frozen exploratory object. This does not upgrade the
two already-inspected tapes into confirmation, causality, economic evidence or a trading signal.
