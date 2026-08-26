# Late-session OFI live exploration — frozen specification

**Protocol ID:** `X-OFI-LATEPARTIAL-2026-08-20`

**Owner approval:** Aryan Ayyar, voice, 2026-08-20 09:37 IST

**Frozen before the first outcome-producing checkpoint:** yes

**Source capture:** `ofi-late-partial-20260820`, first retained row
`2026-08-20T09:21:46.898569+05:30`, NIFTY August 2026 future, Standard/Full + depth20 +
depth200

**Order authority:** none

## 1. Claim boundary

This is a separately identified, growing-sample **partial-session exploratory exercise**. It is
not `R-OFI-FULLSESSION-2026-08-20`, cannot repair or substitute for that failed registered run,
is not `H-SIG21` calibration, is not confirmatory, and cannot create or promote a signal. Every
artifact must carry `confirmatory_eligible=false`, `registered_replication_eligible=false`,
`sig21_calibration_eligible=false`, and `order_entry_enabled=false`.

Live checkpoints reuse outcomes repeatedly as the tape grows. They are path diagnostics, not
independent replications, held-out confirmations, or evidence of stability. No axis, lead, model,
window, horizon, control, or gate may be changed after a live checkpoint is inspected.

## 2. Sample and timing

- One append-only capture beginning at its actual first retained row around 09:21:46 IST.
- Every checkpoint is an immutable APFS copy-on-write snapshot of a complete JSONL prefix.
- The final checkpoint clips at 15:40:00 IST; post-close buffer rows are excluded.
- Receive time is the causal clock. Gap, split and embargo conventions remain those of the source
  analyses: 0.5-second causal gap, chronological 70/30 split, 120-second embargo.
- A checkpoint records source path, byte length, first/last receive timestamps, row/channel counts,
  snapshot SHA-256 and executable commit. A malformed final line, mixed identity, wrong date,
  missing channel, or non-monotone boundary blocks that checkpoint.

## 3. Frozen analysis families

### 3.1 Price-keyed multi-level OFI

Run the complete `X-OFI-DAT20-03` machinery unchanged:

- accumulation windows 0.5/1/2/5/10 seconds;
- depth cutoffs 1/5/10/20/50/100/200;
- future horizons 1/2/5/10/30 seconds;
- all 175 future cells, nested-depth contributions, past mirror, same-window diagnostics,
  coefficient signs and dependence-aware error comparisons.

The pre-named headline is top-10 price-keyed OFI, 10 seconds to the next 10-second return.

### 3.2 Exact CKS level-one OFI

Run the complete amended `X-CKS-L1-OFI-DAT20-04` machinery unchanged:

- accumulation windows 0.5/1/2/5/10 seconds;
- core future horizons 0.5/1/2/5/10 seconds;
- separately labelled 30-second robustness arm;
- 30 cells, exact eight-component decomposition, raw OFI, causal depth control,
  depth-normalised pressure, component intensities, past mirrors and top-10 comparison arm.

The pre-named headline is depth-normalised CKS pressure, 2 seconds to the next 2-second return.

### 3.3 M0–M6 predictor horse race

Run the complete `X-OFI-HORSERACE-DAT20-05` machinery unchanged on the one checkpoint tape:

- M0 depth state, M1 static L1 imbalance, M2 signed trade imbalance, M3 raw CKS, M4 price-keyed
  multi-level OFI, M5 causally depth-adjusted multi-level OFI and M6 combined Ridge;
- all h1/h2 combinations in 0.5/1/2/5/10 seconds;
- future/past/same-window arms, normalised trade/CKS sub-arms, combined-model ablations,
  per-band contributions, support/intensity tables and collinearity diagnostics.

Cross-tape stability is unsupported by construction. The 30-second gate is forced closed and zero
conditional 30-second horse-race cells are fitted.

## 4. Live checkpoint schedule

Frozen checkpoints are 09:45, 11:30, 13:30 and 15:42 IST. A late start processes the earliest
unaccepted checkpoint whose scheduled time has passed; accepted checkpoints are never overwritten.
All three families run sequentially with one heavy reader at a time.

- Interim checkpoints use 100 bootstrap replicates. Beta and R² estimates are identical to the
  full setting; only dependence-resampling precision is lower and must be labelled preliminary.
- The 15:42 terminal checkpoint uses 400 replicates and the exact `[first retained row, 15:40]`
  partial-session clip.
- If a checkpoint remains active when the next time arrives, the controller finishes it before
  taking the next immutable snapshot; no sibling fan-out is allowed.

## 5. Live headline contract

Each accepted checkpoint publishes a machine JSON and Markdown summary containing:

1. snapshot support and source hash;
2. the two pre-named leads before any reranking;
3. for each lead: raw/standardised beta, held-out R², incremental held-out R², past-mirror
   increment, sample sizes and available dependence statistics;
4. horizon-by-horizon M0–M6 leaders, their beta dictionaries and incremental held-out R²;
5. maximum absolute feature correlation, condition number and maximum VIF for the reported horse
   cell, explicitly as collinearity diagnostics rather than predictor-return correlations;
6. CKS component/intensity shares and multi-level band contributions;
7. explicit warnings that rolling checkpoints overlap, the sample is partial, rankings are
   exploratory, cross-tape stability is unavailable and the 30-second gate is closed.

Correlation language must name the object. Feature-feature correlation/collinearity may not be
described as correlation with future returns. Predictor-return association is represented by the
reported beta and held-out R² unless a separately computed Pearson statistic is explicitly
labelled and its support stated.

## 6. Outputs and acceptance

For each checkpoint `<HHMM>`:

- `snapshots/<HHMM>/tape_*.jsonl` and snapshot metadata;
- scalar JSON + 175-row grid JSONL + nested-depth JSONL;
- CKS JSON + 30-row grid JSONL + component JSONL;
- horse JSON + future/past JSONL + ranking/ablation/intensity/support/gate CSVs;
- `live_summary.json`, `LIVE-SUMMARY.md`, hash manifest and accepted checkpoint receipt.

A checkpoint is accepted only when every required file exists, parses, has the complete frozen
cell counts, carries the partial-exploratory claim boundary, matches the snapshot hash and passes
cross-artifact support checks. `data_insufficient` cells remain explicit; they are not fabricated
or removed.

Terminal completion requires the 15:42 checkpoint, exact through-15:40 clip, 400-replicate family,
all hashes and schemas, and a final report. Live reporting jobs may inspect accepted receipts but
never own, restart or alter computation.

## 7. Resource, recovery and safety

- Capture has priority. One nice-priority analysis child at a time; BLAS thread counts are capped.
- Minimum free disk 100 GiB and minimum available memory 4 GiB before snapshot/analysis.
- Source capture is read-only. Snapshots and accepted artifacts are immutable.
- Transient copy/read failures receive at most two bounded retries. Deterministic schema, identity,
  hash, model or scientific-gate failures are not retried unchanged.
- A controller restart resumes from accepted checkpoint receipts and never duplicates a live child.
- No credential, order module or trading endpoint is imported or invoked.
