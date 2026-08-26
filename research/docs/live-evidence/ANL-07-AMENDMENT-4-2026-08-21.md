# ANL-07 owner amendment 4 — six-frame live replacement

## Scope and authority

Aryan Ayyar explicitly approved this model change on 2026-08-21: replace the twelve-frame,
0.10-volatility-point held-out-reference stability policy with six frames and 0.50 volatility
points. The causal parameter-smoothing half-life remains 60 seconds. This is still a read-only
research classifier with no signal, fill, P&L, arbitrage, or order authority.

Implementation commit: `3aa8e93d661d7e82e53864957be04042159f445c`.

## Verification before deployment

- Focused detector/dashboard tests: 44 passed.
- Full repository suite: 712 passed with 11 known numerical warnings.
- Whole-repository Ruff: passed.
- Strict mypy: passed on 72 source files.
- Compileall: passed.
- Dashboard/API regression proves the CLI and policy payload both carry six frames and 0.50
  volatility points; the rendered table no longer hard-codes a twelve-fit label.

## Live replacement

The superseded direct-dashboard segment was stopped after its append-only tape reached
10,245,514,600 bytes at 13:35:42 IST. It remains preserved at:

`/Volumes/Aryan/NSE/2026-08-21/raw/anl03-live-20260821/sha-20260821T041315.549698Z-fa190408/tape_sha-20260821T041315.549698Z-fa190408.jsonl`

The replacement follows the current DAT boundary rather than opening a broker connection inside
the dashboard:

- DAT owner tmux: `shaurya-dat-chain-20260821-a4`, launch PID 53968.
- DAT dataset: `sha-20260821T080612.138551Z-9b5bd89e`.
- DAT tape:
  `/Volumes/Aryan/NSE/2026-08-21/raw/sha-20260821T080612.138551Z-9b5bd89e/tape_sha-20260821T080612.138551Z-9b5bd89e.jsonl`.
- Dashboard follower tmux: `shaurya-essvi-dashboard-20260821-a4`, launch PID 54075.
- Endpoint: `http://100.65.47.57:8765/`.
- Tracked universe: 452 instruments across 25 August, 1 September, and 29 September 2026.

At 13:36:40 IST the replacement had a successful arbitrage-clean fit, 446.9 packets/second,
0 reconnects, and a 0.052-second feed age. The API exposed the binding policy exactly:

```text
reference_smoothing_half_life_seconds      60.0
reference_smoothing_min_frames              6
reference_stability_frames                  6
reference_max_iv_range_points               0.50
reference_max_raw_smoothed_iv_gap_points    0.50
```

After the six-frame warm-up, the 13:37:21 frame tested 246 contracts and rejected 9 for reference
instability. For context, the superseded process's 13:18:16 frame tested 52 and rejected 208 under
the old policy. This is a same-day live screen comparison, not a controlled same-tape causal
estimate, but it confirms that the intended gate is no longer excluding most of the cross-section.

A full-page headless-Chrome render at approximately 13:39 IST showed the new on-screen labels
`REFERENCE WINDOW 6 frames`, `IV TOLERANCE 0.50 pp`, and `STABILITY RANGE pp`. That frame had two
exact-confirmed candidates pending and no active episode. By 13:40:09 the pending set had cleared
without activation, showing that the unchanged two-frame persistence gate continued to reject
one-frame candidates.

The first post-amendment active episode then appeared: `MP-20260821-000001`, 29 September 25300
CE, cheap. It was first seen at 13:41:05, confirmed at 13:41:10, and invalidated at 13:41:20 after
15.27 seconds. The target executable IV did not close the frozen target; the trace was
reference-market-led, with target/reference IV contributions of -0.0040/+0.1082 volatility
points and a -INR 28.95/lot frozen-delta markout proxy. It is retained as an invalidated episode,
not a corrected opportunity. This is direct evidence that the looser stability gate increases
sensitivity while the unchanged frozen-target attribution and invalidation rules still reject a
reference-closed residual.

## Evidence level

The amended policy, API, DAT-follow transport, and rendered dashboard are **Live verified**. The
observed candidate counts are live descriptive evidence only; no profitability, fill, or latent
true-value claim follows.
