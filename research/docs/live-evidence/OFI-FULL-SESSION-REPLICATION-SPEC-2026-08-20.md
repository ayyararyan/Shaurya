# OFI full-session replication — frozen protocol for 2026-08-20

**Protocol ID:** `R-OFI-FULLSESSION-2026-08-20`

**Status:** frozen before the 2026-08-20 tape exists

**Registration clock:** the first pushed commit containing this file

**Owner instruction:** Aryan Ayyar, voice, 2026-08-19 ~20:59 IST

**Execution date:** 2026-08-20

**Market:** NSE equity derivatives, regular session 09:15:00–15:40:00 IST

**Instrument:** same-day resolved NIFTY front-month future

**Order authority:** none; market-data subscriptions and read-only analysis only

## 1. Claim boundary

Tomorrow's tape is a prospective, full-session **replication of machinery whose outcomes have
already been inspected** on the two `DAT-20` tapes. It is not a virgin hypothesis sample and is
not eligible to register or confirm a trading signal.

- `sample_role = prospective_full_session_replication`
- `outcome_join_allowed = true`
- `confirmatory_eligible = false`
- `sig21_calibration_eligible = false`
- `H-SIG21` remains untouched and receives zero calibration-session credit from this run.

The report must separate:

1. **fixed-lead replication**, containing only the two leads named in §6 before tomorrow's data;
2. **complete reranking**, containing every frozen cell and explicitly labelled exploratory.

One day can reject a claimed reproduction, reveal time-of-day or support defects, or justify a
later registration. It cannot promote a signal.

## 2. Market clock and capture window

NSE's equity-derivatives regular session is 09:15:00–15:40:00 IST from 2026-08-03 onward. The
regular-session span is therefore 385 minutes = **23,100 seconds**. The controller may connect
before 09:15 and may retain a post-close buffer, but analysis is clipped by `receive_ts` to the
closed interval `[2026-08-20T09:15:00+05:30, 2026-08-20T15:40:00+05:30]`.

Requested duration alone is never evidence of full-session coverage. Acceptance requires actual
retained rows on or before the opening boundary and on or after the closing boundary, subject to
the channel-specific conditions in §4. A tape that starts late, ends early, loses a required
channel, crosses the trading date, or cannot prove the bounds is preserved but marked ineligible.

The dated market-clock rule is:

- trading dates before 2026-08-03: close 15:30 IST;
- trading dates on or after 2026-08-03: close 15:40 IST.

Official sources: NSE Market Timings, NSE Closing Auction Session, and NSE circular
`FAOP71777.pdf` (2026 F&O holidays). 2026-08-20 is not an F&O holiday.

## 3. Instrument resolution

The controller refreshes the immutable Dhan instrument master dated 2026-08-20 and selects the
unique mapping satisfying all of:

1. NSE F&O future;
2. NIFTY underlying (not BANKNIFTY, FINNIFTY or MIDCPNIFTY);
3. expiry on or after 2026-08-20;
4. minimum such expiry;
5. unique security ID and exact symbol identity in the same-day master.

No stale security ID may be carried from 2026-08-19. Ambiguity or absence fails before a socket is
opened.

## 4. Raw capture contract and acceptance

One process and one append-only run capture the same future on all three channels:

- Standard Full/5-level, including the capture-time classified trade fields;
- depth20;
- depth200.

All three are required. `--no-standard` and `--no-depth20` are forbidden and depth200 must be
enabled. The capture profile is mutually exclusive with `--sig21-calibration`.

The capture artifact records the protocol ID, registration commit, same-day master hash, resolved
identity, requested and regular-session bounds, required channels, channel packet counts, first
and last retained `receive_ts` per channel, reconnect and heartbeat counters, tape hash, and this
claim boundary.

An accepted capture requires:

1. collector exit status completed and append-only manifest complete;
2. non-zero packets from Standard/Full, depth20 and depth200;
3. overall retained rows spanning both regular-session boundaries;
4. depth20 and depth200 each have a last complete book at or after 15:40 and a complete book no
   later than the opening tolerance described below;
5. Standard/Full has an observed row on both sides of the session span; trade silence itself is
   not failure;
6. no mixed instrument/run/date identity;
7. manifest tape hash equals the recomputed SHA-256;
8. enough free disk remains for atomic derived outputs and the raw tape is permanent.

Because a publication need not land at the exact nanosecond boundary, the opening check admits the
first complete depth state through 09:15:02 IST only when the socket was connected before 09:15;
the closing check admits the first complete depth state through 15:40:02 IST. These tolerances are
coverage checks, not extra analysis time. Every model is still clipped to the exact regular
session. Any wider tolerance requires a versioned amendment before capture.

Reconnects do not automatically invalidate the tape. Every gap is surfaced and the report must
state whether common support remains continuous enough for the frozen 120-second embargo and
window definitions. A partial run is never deleted and is never silently concatenated with a
second run.

## 5. Common causal sample

All three scans consume the identical accepted tape and exact clipped row set. They use capture
receive time, not exchange timestamps that the deep feeds do not supply. Future outcomes use the
depth20 midpoint convention already frozen in the source scans.

- causal gap `Z = 0.5 s`;
- chronological 70/30 split inside the one session;
- 120-second embargo at the split;
- no same-day refit using test outcomes;
- all past-mirror, same-window, support and dependence diagnostics retained;
- no fabricated cross-tape sign-stability statistic: one session is one tape;
- any condition requiring at least two tapes is false/not-supported, never imputed true.

## 6. Frozen analysis family

The post-close controller reruns all three source families without choosing cells after seeing
tomorrow's outcomes.

### 6.1 Price-keyed scalar OFI (`X-OFI-DAT20-03` machinery)

- accumulation windows: 0.5, 1, 2, 5, 10 seconds;
- depth cutoffs: 1, 5, 10, 20, 50, 100, 200 levels;
- future horizons: 1, 2, 5, 10, 30 seconds;
- complete 175-cell future grid plus nested-depth, past-mirror and same-window diagnostics.

The **fixed scalar lead** is top-10 price-keyed OFI, `h1=10 s`, `h2=10 s`. Its coefficient,
incremental held-out R², dependence checks, support and past mirror are printed before any new
ranking.

Cutoffs 20 and 200 are both retained so the requested 20-versus-200 depth comparison is direct;
no post-hoc intermediate cutoff may replace them.

### 6.2 Exact CKS L1 OFI (`X-CKS-L1-OFI-DAT20-04` machinery)

- accumulation windows: 0.5, 1, 2, 5, 10 seconds;
- core future horizons: 0.5, 1, 2, 5, 10 seconds;
- separately labelled 30-second robustness arm;
- complete 25 core + 5 robustness cells;
- exact eight-component transition decomposition, depth controls, pressure arms, component
  intensities and the already-declared top-10 comparison arm.

No additional CKS lead is promoted from this run.

### 6.3 Predictor horse race (`X-OFI-HORSERACE-DAT20-05` machinery)

Run M0–M6, all declared normalised sub-arms, complete future and past families, same-window
diagnostics, combined-model ablations, support/intensity tables and per-band contributions on
`h1,h2 in {0.5,1,2,5,10}`.

The **fixed horse-race lead** is depth-normalised CKS (`M3b`), `h1=2 s`, `h2=2 s`. Report its
incremental held-out R² over M0, coefficient, support, dependence checks and past mirror before
the full reranking.

The 30-second gate stays closed on one tape because its frozen conditions require non-negative
increments and stable direction across at least two tapes. Zero 30-second model cells are fitted
unless a pre-capture amendment changes that rule; none is authorised here.

## 7. Required outputs

Every output is written first to a unique partial directory, hashed, then atomically promoted.
Required terminal artifacts are:

1. raw capture run directory, metrics, quality audit and append-only manifest;
2. coverage acceptance receipt with exact first/last timestamps by channel;
3. price-keyed OFI JSON, grid JSONL and nested-depth JSONL;
4. CKS JSON, 30-cell JSONL and component/intensity JSONL;
5. horse-race JSON, future/past JSONL, ranking/ablation/intensity/support/gate CSVs;
6. fixed-lead comparison JSON and Markdown summary;
7. one hash manifest covering every derived artifact and the raw tape;
8. exact commands, code commit, registration commit, Python version, seeds and bootstrap counts;
9. final run report stating acceptance, exclusions, gate state and whether each prior lead
   replicated in sign and incremental held-out R².

The report must include complete grids even if the fixed leads fail. It must not call a new argmax
a winner, alpha, signal, confirmation, or registration candidate without a later owner-approved
pre-registration on untouched sessions.

## 8. Runtime, recovery and safety

The controller runs in a named tmux session, maintains atomic `state.json`, records child PIDs and
heartbeats, and never treats the chat/cron process as the computation owner. It preflights code
commit equality, secrets-file permissions without printing values, disk, master identity, clock,
duplicate sessions and required executables.

Stages are idempotent and resumable: `preflight`, `wait_for_open`, `capture`, `accept_capture`,
`scalar_ofi`, `cks_l1`, `horse_race`, `summarise`, `complete`. An accepted stage is skipped only
when its receipt and hashes still verify. A failed capture blocks analysis. A failed analysis
preserves the tape and resumes from the failed stage without recapture.

No order-placement module, endpoint or credential is imported or invoked. No live order is
authorised by this protocol.

## 9. Falsifiers and interpretation

A fixed lead fails to replicate if its incremental held-out R² is non-positive, its coefficient
sign reverses, or its future result is no stronger than its own past mirror. A full-grid argmax
does not rescue a failed fixed lead.

Even a positive fixed-lead replication remains an exploratory selection-aware observation from
one full session. The next legitimate step would be a new, pushed registration on untouched
multi-session tape with ex-ante power, multiplicity and economic-size gates.
