# CCZ OFI Migration — Frozen Specification

**ID:** `D37 / CCZ-OFI-MIGRATION-2026-08-20`
**Status:** Frozen on Aryan's explicit instruction, 2026-08-20 12:26 IST.
**Authority:** Aryan, by direct instruction: *"wherever we're implementing OFI and multilevel
OFI, it has to be CCZ. Meaning - if we do OFI, rather do it properly."*
**Reference:** Cont, Cucuringu & Zhang, *Cross-Impact of Order Flow Imbalance in Equity
Markets*, Quantitative Finance (2023); arXiv:2112.13213v4. Equations cited below are that
paper's numbering.
**Base commit:** `be2dd99` on private `ayyararyan/Shaurya`.
**Working branch:** `ccz-ofi-migration` in isolated clone `/Users/maheit/Documents/Shaurya-ccz`.

---

## 0. Change control (§14)

**Requirements affected:** the OFI estimator family underlying `X-OFI-DAT20-03`,
`X-CKS-L1-OFI-DAT20-04`, `X-OFI-HORSERACE-DAT20-05`, `X-OFI-LATEPARTIAL-2026-08-20` and
`X-OFI-DASHBOARD-2026-08-20`.

**Current requirement.** Three mutually inconsistent objects coexist:

1. `deep_book_ofi.price_keyed_ofi_transition` — price-keyed signed innovations accumulated
   into a **running sum across levels** (`cumulative_by_depth[L] = Σ_{rank≤L}`), **unnormalised**.
2. `ofi_horserace` M5 — disjoint band flows each divided by **that band's own** mean depth.
3. `cks_l1_ofi` / M3b — level-1 CKS event increment divided by mean level-1 half-depth.

**Why the change is necessary.** None of the three is the CCZ multi-level OFI.
Object 1 cumulates levels, which CCZ never do, and applies no depth scaling.
Object 2 uses a per-band denominator; CCZ Eq. (3) uses a **single common denominator** across
all M levels precisely so that relative magnitudes across levels survive the scaling.
Object 3 is correct CKS (2014) but is single-level and therefore not a multi-level object at all.
Reporting any of them as "the CCZ multi-level OFI" would be false.

**Proposed change.** Replace objects 1 and 2 with a faithful CCZ implementation. Retain the
level-1 CKS increment, which is CCZ Eq. (1)'s base case and is already correct.

**Effect on interpretation.** Results become directly comparable to the published CCZ numbers
and to Kolm–Turiel–Westray. Existing `X-OFI-DAT20-03` / `-04` / `-05` / `-LATEPARTIAL` numbers
are **not** invalidated — they measure what they measure — but they are permanently relabelled
as non-CCZ constructions and may not be described as multi-level CCZ OFI in any writeup.

**Effect on comparability.** Pre-migration and post-migration numbers are **not** comparable
and must never be pooled or presented in one table without an explicit estimator column.

**Approval:** Granted by Aryan, 2026-08-20 12:26 IST.

---

## 1. Definitions to implement

### `EST-CCZ-01` — per-level order flow (Eq. 2 base terms)

For consecutive book states `n-1`, `n` and level `m`, **rank-keyed** (compare the level-`m`
price across the two states — *not* price-keyed):

```
OF^{m,b}_n =  q^{m,b}_n                      if P^{m,b}_n >  P^{m,b}_{n-1}
              q^{m,b}_n - q^{m,b}_{n-1}      if P^{m,b}_n =  P^{m,b}_{n-1}
             -q^{m,b}_n                      if P^{m,b}_n <  P^{m,b}_{n-1}

OF^{m,a}_n = -q^{m,a}_n                      if P^{m,a}_n >  P^{m,a}_{n-1}
              q^{m,a}_n - q^{m,a}_{n-1}      if P^{m,a}_n =  P^{m,a}_{n-1}
              q^{m,a}_n                      if P^{m,a}_n <  P^{m,a}_{n-1}
```

### `EST-CCZ-02` — level-m OFI over horizon h (Eq. 2)

```
OFI^{m,h}_t = Σ_{n ∈ (t-h, t]} [ OF^{m,b}_n - OF^{m,a}_n ]
```

**There is no sum over levels.** Level `m` uses level `m` only. Any `Σ_{k=1}^{m}` in the
implementation is a defect.

### `EST-CCZ-03` — depth scaling (Eq. 3), single common denominator

```
ofi^{m,h}_t = OFI^{m,h}_t / Q^{M,h}_t

Q^{M,h}_t = (1/M) Σ_{m=1..M} [ (1 / (2·ΔN(t))) Σ_{n ∈ (t-h,t]} ( q^{m,b}_n + q^{m,a}_n ) ]
```

`ΔN(t)` is the number of book events in the interval. **The same scalar `Q^{M,h}_t` divides
every level.** A per-level or per-band denominator is a defect. Floor the denominator to avoid
division by ~zero; record every flooring event in diagnostics.

### `EST-CCZ-04` — Integrated OFI (Eq. 4)

```
ofi^{I,h}_t = w_1ᵀ · ofi^{(h)}_t / ‖w_1‖_1
```

`w_1` is the first principal component of the multi-level normalised OFI vector, estimated
**on training data only** and applied unchanged out of sample. Report explained-variance ratio
per fit. Sign-fix `w_1` so its dominant loading is positive, and record the applied sign.

### `EST-CCZ-05` — declared aggregation arms

- `PI^[m]` (Eq. 19): levels entered as separate regressors, `Σ_{k=1..m} β^k ofi^k`.
- Integrated OFI (`EST-CCZ-04`) — **primary**.
- Simple average across levels — CCZ Appendix A benchmark, retained for comparison.
- Best-level only (`m=1`) — CKS (2014) baseline.

### `EST-CCZ-06` — level count

`M = 10` is the **primary**, matching CCZ. Declared robustness arms: `M ∈ {1, 5, 20}`, and
`M = 200` from the depth200 channel. No arm is dropped; deep arms remain declared even though
`X-DEEPBOOK-DAT20-02` already found no incremental gain beyond level 20.

---

## 2. Known limitation, stated not patched

`ID-CCZ-01` — Dhan publishes **snapshots**, not order-by-order messages. Rank-keyed comparison
means a best-quote move shifts every level's identity, so a single price change can register
as flow at many levels at once. The retired price-keyed design existed specifically to avoid
this. Faithful CCZ reintroduces it. This is recorded as a **limitation of the estimand under
snapshot data**, and must appear in every artifact and report. It is not to be silently
corrected, and gross arrivals/cancellations remain **unidentified** (`ID-01`).

---

## 3. Scope of code change

| ID | Requirement | Target |
|---|---|---|
| `CCZ-IMPL-01` | New module implementing `EST-CCZ-01..05` | `src/shaurya/signals/ccz_ofi.py` |
| `CCZ-IMPL-02` | Remove cumulative-across-levels construction | `deep_book_ofi.py` |
| `CCZ-IMPL-03` | Remove per-band depth normalisation (M5) | `ofi_horserace.py` |
| `CCZ-IMPL-04` | Rebuild horse-race families on CCZ objects | `ofi_horserace.py` |
| `CCZ-IMPL-05` | Retain level-1 CKS unchanged as Eq. (1) base case | `cks_l1_ofi.py` |
| `CCZ-IMPL-06` | Dashboard consumes CCZ estimators | `analytics/ofi_dashboard.py`, `cli/ofi_dashboard.py` |
| `CCZ-IMPL-07` | Update replication/live-partial drivers | `data/ofi_replication.py`, `data/ofi_live_partial.py` |
| `CCZ-IMPL-08` | Per-unit commit-pin re-check (see §4) | run controllers |

## 4. Independent defect found during scoping

`OPS-CCZ-01` — `overnight-runs/ofi-partial-live-20260820/code/controller.py:406` checks the
pinned commit **only in `preflight`**, which runs once. The repository moved from `3147ccb` to
`8ae6be5` (10:27), `0749df8` (11:08), `8573a52` (11:16), `2337203` (11:37) and `7cbd816`
(12:22). The **11:30 checkpoint therefore ran off-pin**, with HEAD changing at 11:37:43 between
its CKS and horse-race stages, while its artifacts record `code_commit: 3147ccb`.

`git diff --stat 3147ccb 7cbd816` touches only dashboard, mispricing, eSSVI and surface files —
nothing under `src/shaurya/signals/` or `src/shaurya/data/ofi_*`. The estimator path was
byte-identical, so **the 11:30 numbers are numerically valid; only the provenance label is
false.** Fix: re-check pin and worktree cleanliness before **every** unit, fail closed, and
record the observed HEAD per stage rather than the constant.

## 5. Acceptance tests

- `VAL-CCZ-01` Per-level OFI on a hand-built two-snapshot fixture matches Eq. (2) by hand.
- `VAL-CCZ-02` No code path sums OFI across levels — asserted by regression test.
- `VAL-CCZ-03` All M levels share one denominator: scaling any single level's raw OFI by
  `Q^{M,h}` reproduces `ofi^m` exactly.
- `VAL-CCZ-04` PC1 is fit on train only; a leakage test fails if test rows influence `w_1`.
- `VAL-CCZ-05` `‖w_1‖_1` normalisation makes the integrated weights sum to 1.
- `VAL-CCZ-06` Sign convention: a pure bid-side size increase yields positive OFI at that level.
- `VAL-CCZ-07` Full suite, ruff, strict mypy clean; no lookahead assertion regressions.
- `VAL-CCZ-08` Every artifact carries `estimator: "CCZ"`, the level count `M`, the EVR, and
  the `ID-CCZ-01` limitation string.

## 6. Explicit exclusions

- The live capture `ofi-late-partial-20260820` is untouched.
- No order path, no SIG-21 credit, no confirmatory status. This is an estimator migration.
- Pre-migration artifacts are preserved and relabelled, never deleted or pooled.
