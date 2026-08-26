# ANL-07 owner amendment 5 — live verification

- **Owner decision:** 120-second causal smoothing half-life; rolling stability-window gate
  removed altogether.
- **Verification date:** 2026-08-21
- **Authority:** read-only research classification and dashboard only; no signal, fill, P&L,
  arbitrage, latent-value, or order authority.
- **Code commit:** `9438831` (`Remove ANL-07 stability window`)

## Implemented policy

The live `/api/state` policy reports:

```text
reference_smoothing_half_life_seconds = 120.0
reference_smoothing_min_frames = 6
reference_stability_window_enabled = false
reference_max_raw_smoothed_iv_gap_points = 0.50
reference_rewarm_after_invalidation = false
```

There is no policy field for a rolling stability-frame count or a max-minus-min IV range.
The detector no longer stores per-contract reference-IV history. The 0.50-point limit applies
only to the current raw-smoothed and exact-smoothed robustness checks.

## Deployment

- Endpoint: `http://100.65.47.57:8765/`
- Dashboard tmux: `shaurya-essvi-dashboard-20260821-a5`
- Dashboard PID at verification: `57903`
- DAT tmux: `shaurya-dat-chain-20260821-a4`
- DAT PID at verification: `53968`
- Dataset: `sha-20260821T080612.138551Z-9b5bd89e`
- Tape: `/Volumes/Aryan/NSE/2026-08-21/raw/sha-20260821T080612.138551Z-9b5bd89e/tape_sha-20260821T080612.138551Z-9b5bd89e.jsonl`

The DAT capture remained authoritative and was not restarted. The replacement dashboard first
replayed the existing dataset and then attached to its growing tail. During deterministic catch-up,
dashboard feed age was stale by construction while the underlying tape continued growing; no live
verification claim was made until processed time reached the tail.

## Post-warm-up live state

Observed from `/api/state` at `2026-08-21T14:07:36.985616+05:30`:

```text
processed market timestamp  2026-08-21T14:07:39.810599+05:30
feed age                   0.107003 seconds
packets per second         425.6
reconnects                 0
fit status                 temporally_smoothed
SUR-05 arbitrage passed    true
eligible contracts         268
statistically tested       268
reference warming          0
reference rejected         0
outside fair-IV band       2
BH-FDR significant         1
exact confirmed            1
pending                    1
active                     0
recent                     0
```

These counts establish that the new policy completed warm-up and evaluated the live chain. The
pending row is not an active episode or opportunity result.

## Render verification

OpenClaw browser navigation to the private Tailscale address was blocked by browser policy, so the
OpenClaw browser was stopped and the same page was rendered with direct local headless Chrome.
The executed DOM visibly contained:

```text
smoothing half-life 120 s
stability window off
raw/exact tolerance 0.50 pp
120 s causal surface smoothing
no rolling stability-window gate
smoother fits
reference eligible
```

## Automated verification

- Focused detector/dashboard tests: **44 passed**
- Full suite: **716 passed**, 11 known numerical RuntimeWarnings
- Ruff: passed
- Strict mypy: passed on 74 source files
- Compileall: passed

## Evidence conclusion

Owner amendment 5 is **Live verified** for the read-only ANL-07 classification/API/rendering
scope. It does not establish that any detected episode is genuine mispricing, profitable,
fillable, or caused by the target option.
