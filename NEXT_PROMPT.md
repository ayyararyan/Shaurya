# Shaurya — Next-Session Prompt

**Prepared:** 2026-08-17, last updated 2026-08-19 evening (signal-mining reset by Aryan)
**Use on return:** the 2026-08-19 **evening** session. Read the reset handoff immediately below;
it supersedes the older afternoon agenda as the next conversation.
**Repository:** private `ayyararyan/Shaurya`
**Canonical status ledger:** `TASKS.md`

## RESET HANDOFF — EVENING 2026-08-19, READ THIS FIRST

Aryan explicitly approved the **joint quoting configuration** as the right direction, asked for
the top academic literature to be researched and recorded, and then reset the session. That work
is complete in the repository:

- paper-by-paper synthesis, boundaries and claim–evidence ledger:
  `docs/research/joint-option-quoting-literature-2026-08-19.md`;
- book-state consequences and registered tests: `docs/sig-claims/book-state.md`;
- `D29`: the scale-specific hypothesis method in `docs/sig-claims/METHOD.md` is binding across
  every feature class. The intended method was previously called “D28” in conversation, but
  another same-day decision had already occupied that stable ID; stable IDs are never reused, so
  it is correctly recorded as `D29`;
- `D30`: the primary decision object is a simultaneous chain-level put/call quote configuration,
  while per-quote fill and markout remain measurement primitives. Quote skew/passive option fills
  are the routine inventory-control mechanism and futures are a residual breach valve. The
  controller form is **not** chosen.

### The next conversation — do this, not more hedge architecture

Aryan's exact intent: *“today evening we need to continue our debate on the signal mining (as we
slightly drifted from it for the right reasons though) and take on the next class of objects.”*

The next taxonomy cell after event flow (`EF`) and book state (`BK`) is **price-path-derived
objects (`PP`, `SIG-04`)**: lagged returns, realised volatility/variation, variance ratio,
microprice tilt, spread/impact transforms, Kyle lambda and Amihud-type measures. Proceed as in the
BK discussion:

1. first answer **what each PP object influences** at the short horizon;
2. then answer **how that changes a maker's joint quoting configuration** — fill, conditional
   markout, withdrawal/skew, inventory tolerance, or flattening — without wandering into mechanism
   stories unless the mechanism changes the sign of the action;
3. invite Aryan's attack and refine the claims;
4. bind accepted hypotheses under `METHOD.md` with `X,h₁,f₁,Y,h₂,f₂,Z`, stratum, `K`, `N_eff`,
   `G`, MDE, latency admissibility and a real falsifier before any execution.

Do **not** reopen whether the estimand is per quote or joint configuration; `D30` settles it. Do
not select a control model from the literature. `BK-11/H1`, `BK-13/H1`, `BK-14/H1` and
`BK-15/H1` are registered future tests, not the evening debate. `SIG-21` remains open and must be
pre-registered before its outcomes are inspected, but Aryan explicitly set `PP` as the next
conversation.

The earlier **AFTERNOON AGENDA** below is retained as historical operational context. It no longer
defines the next conversational task.

## AFTERNOON AGENDA — SET BY ARYAN 2026-08-19 ~12:24 IST, READ THIS FIRST

He reset the session after `ANL-03` and `DAT-17` both landed, and named three items for the
afternoon/evening, **in this order**. His sequencing was explicit: *"Today afternoon, we discuss
first on the feed and then take some decisions."* Discussion precedes decision. Do not arrive with
decisions pre-made.

1. **`DAT-18` — interpret the level-wise feed properly.** His words: *"the level wise feed thing
   needs to be seriously interpreted well."* All three tiers are now measured; the numbers are not
   the interpretation. What the width-versus-depth trade actually costs in information is the
   question. This is a conversation with him, not an agent task.
2. **`DAT-19` — how to store the data well.** *"the data will not start becoming big"* — read in
   context as *is about to become big*: the live dashboard is writing ~40 MB/minute. Format,
   compression, partitioning, seekable replay index, integrity, tiering. Retention stays permanent
   (2026-08-18); this is about cost and access, never about deleting the raw tape, which `D12`
   retains specifically so `SIG-18` remains possible.
3. **`ANL-05` — dashboard aesthetics.** He called it *"minor but worthy"*. Presentation only;
   thresholds, labels and displayed quantities are specification and must survive untouched.

`DAT-09` becomes answerable once `DAT-18` is discussed — the width/depth numbers it was waiting on
now exist. The SIG story-by-story debate against MK-01–MK-13 remains the main unstarted
intellectual work and sits behind these three.

### Live at the moment of the reset

**The `ANL-03` dashboard is running and should be left running** — `http://127.0.0.1:8765/`,
started 12:04 IST, PID recorded in the session log, NIFTY 452 instruments across 2026-08-25 /
2026-09-01 / 2026-09-29, `--serve-seconds 13200 --post-stream-seconds 900`, so it stops itself at
about 15:47 IST. Aryan asked to *"keep seeing the feed for the rest of the day"* and separately
gave permission to kill it if it proved heavy. It is **not** heavy — measured 3.7% CPU and 147 MB
RSS — so it stays up. Two reasons beyond his request: it is the only run that will cover an
afternoon session and a real market close, both of which `ANL-03` lists as unverified; and it will
render post-close feed death, exercising the same path that was demonstrated by hand this morning.
Cost is disk only: ~40 MB/min into `data/live-captures/anl03-live/`, about 8 GB more by the close,
against 1.4 TB free. If it must be stopped, stopping it loses the afternoon coverage — say so
rather than killing it silently.

### The operational mess of the late morning, resolved — do not re-diagnose it

**Two DAT-17 agents ran concurrently.** Two OpenClaw main sessions were live on the same Telegram
chat and each spawned its own `shaurya_dat17_depth200_bounds`: `673f8911` at 11:49:05 (28m22s) and
`2033be0d` at 11:51:05 (16m44s). Both completed, both wrote to this clone, and the tree was
deduplicated at `b4a2975`. This is why Aryan received the DAT-17 report three times in slightly
different words. Consequence recorded in the `DAT-17` ledger row: sockets briefly hit three for
~35 s, the authoritative capture was already complete and unaffected, the duplicate tape was
excluded. **Nothing needs re-running.**

**No agent died.** Every subagent today ended `done` or `timeout` with its work committed; the
`shaurya_anl03_surface_opus`, `673f8911` and `2033be0d` runs all ended `done`. What died were
*turns*: the "Something went wrong" at 12:24:29 was the known `openclaw/openclaw#113149`
empty-response fallback restart. Gateway-log signature count is now **17**, up from 16 at 11:00
and 14 the previous day — still roughly one a day and unfixed upstream. Re-check:
`grep -c "outBytes=0 outHash=e3b0c44298fc" ~/Library/Logs/openclaw/gateway.log`

**The cron gate was retired.** DAT-17 was first queued as an `on-exit` cron job to sequence it
behind `ANL-03`. The gate fired correctly; the payload failed twice with
`CronSessionLifecycleClaimError`, and because the job carried `deleteAfterRun` it had already been
removed at fire time, leaving nothing to retry. Full write-up in the workspace `TOOLS.md`. **Rule:
do not use cron to sequence one agent behind another — use `sessions_spawn`.**


## STATE AT THE 2026-08-19 ~11:20 IST RESET — READ THIS FIRST

**`origin/main` is at the commit recorded by the final push of this session. Working tree clean.
Nothing of mine is unpushed.**

### One agent was running when the reset happened

`shaurya_anl03_surface_opus` — run `d0bce3c8-a6b7-49dc-a0b7-ff311efbd33c`, session
`agent:main:subagent:6405307b-41cd-459f-9814-f0082de7c629`, model **`anthropic/claude-opus-5`**,
working in a **separate clone** at `/Users/maheit/Documents/Shaurya-anl`. Building `ANL-03`, the
live 3D implied-volatility surface dashboard, on Aryan's instruction. Do **not** spawn a
replacement, do not summarise partial output, and do not edit `/Users/maheit/Documents/Shaurya-anl`.

**Two known hazards with that agent, both already handled but both recurring:**

1. **Its `origin` is the local clone, not GitHub.** `Shaurya-anl` was cloned from
   `/Users/maheit/Documents/Shaurya`, so `git push` there does not reach
   `github.com/ayyararyan/Shaurya`. Its commits must be relayed: from the main clone,
   `git fetch /Users/maheit/Documents/Shaurya-anl main`, reconcile, then push. It has been told.
2. **Histories diverge.** Its line and the main clone's ledger line both descend from `4f51e32`
   and were reconciled once already by rebasing the ledger commit onto its line — **no force-push,
   and do not force-push to fix this.** Expect to do it again. There is no file overlap in
   practice: it writes `src/shaurya/analytics/**`, `src/shaurya/cli/**` and its own evidence doc;
   the ledger work touches `TASKS.md`, `CHANGELOG.md`, `NEXT_PROMPT.md`, `docs/`.

**Its verified findings so far, which are real and should not be re-derived:**
- **No retained tape contains options.** Every capture is index-futures only
  (`NSE:NSE_FNO:NIFTY:future:2026-08-25`). The eSSVI fitter needs option quotes, so replay-first
  cannot mean replaying existing tape — an option chain must be captured today, then replayed.
  It has already shipped a Quote/Full chain-capture CLI, forward selection and a chain universe.

### Why ANL-03 was commissioned, in Aryan's words

Before SIG, make the ingestion visible by fitting and displaying the surface live. Three things he
wants answered by **watching**, not by analysis: (1) do we come to know if the data dies or stalls;
(2) what latency is sustained continuously across the whole day; (3) he wants to watch the **3D
surface evolve** in the browser as the session progresses. `D19` governs: **watching only**, on
SUR's existing fit/smoothing cadence, no latency-engineered fit path, never on a quoting path.

**Standing expectation, set with Aryan up front:** `SUR-02` is Dry-run verified against *synthetic*
option books. The eSSVI fitter has never met a real NIFTY chain. Fit failures, arbitrage-gate
rejections and data-insufficient cells on first live contact are **the finding, not a setback**.
The agent is explicitly barred from widening tolerances to make the picture look clean — that would
be a specification change requiring approval.

### The runtime lesson from this session — apply it

**Codex (`openai/gpt-5.6-sol`) stalled twice on this task and produced nothing.**
`shaurya_anl03_live_surface`: 11m08s, 107k prompt/cache, **502 output tokens**, zero commits.
`shaurya_anl03_surface_v2`: 6m, **126 output tokens**, zero commits. Both died after bulk-reading
large source files. The `shaurya_dat11_15_live` agent also ended `timeout` at 1h04m — though it had
committed and pushed everything first, so its work survived.

**Aryan's standing instruction:** if Codex chokes, escalate to `anthropic/claude-opus-5` (alias
`opus5`) rather than retrying the same runtime a third time. **And sequence it** — do not run a
`claude-cli` subagent concurrently with other agents, because the main Telegram session is itself
`claude-cli` and `openclaw/openclaw#113149` lets one session's empty-response recovery kill
unrelated concurrent `claude-cli` processes. The gateway-log signature count was **16** at
11:00 IST on 2026-08-19, up from 14 the previous day — roughly one a day, live and ongoing.
Re-check: `grep -c "outBytes=0 outHash=e3b0c44298fc" ~/Library/Logs/openclaw/gateway.log`

Also give any agent an explicit **commit-within-15-minutes** rule and forbid multi-hundred-line
bulk file dumps. Both stalls followed oversized reads, and both had nothing to show because they
had committed nothing.

### What landed today, all pushed and independently verified

**DAT-11 — 20-level per-message ceiling is exactly 50 instruments.** Monotone acceptance: 2, 27,
40, 46, 49, 50 accepted; 51, 52, 53, 54, 56, 61, 71, 90, 129 all rejected wholesale with zero
packets. Corrects 2026-08-18's claim that 52 worked. Not the documented 5,000.

**DAT-12 — socket-scoped, load-dependent.** 50+50 on one socket: first message delivered all 50,
second delivered nothing; the identical second set on a fresh socket delivered all 50. But a 2+2
run delivered both on one socket, so the old blanket phrase "only the first message is ever
honoured" is too broad.

**DAT-13 — a genuine first-subscription throttle, not liquidity.** Four comparable front-month
index futures on one 200-level socket; rotating the subscription order moved the 328-vs-2 packet
dominance with position. Later instruments got 2 packets in 40 s. A multi-instrument 200-level
socket is **not** a full-rate feed for anything after the first instrument.

**DAT-14 — Live verified** for depth20 alignment on two front-month futures, 10:23–10:33 IST.
313 positive-volume prints (up from 12): 158 buy, 154 sell, 1 unclassified; 311 quote-rule,
**1 live tick-rule fallback** — closing the gap where the fallback had never fired on real data.
Version stamps 313/313. Coalesced 36.1%; signed last prints cover only **44.3%** of increment
volume, worse than the 63% anecdote.

**DAT-15 — Live verified** on all eight retained tapes: 38,572 rows, 482 prints. Healthy-core
median quote age **238.7 ms** (p95 462.6, max 567.4). Proxy flip rate 5/320 = 1.6%. It correctly
separated a healthy core from one reconnect-heavy run (p95 blows to 3.8 s, max 24 s) instead of
averaging the mess away, and correctly labelled its flip statistic a **proxy, not truth**, because
the post-print quote may already reflect the trade.

**DAT-16 — the premise correction, and the most consequential result of the day.**
**Dhan's depth20 channel is a fixed 500 ms snapshot feed, not an event feed.** Grouping by distinct
receive timestamp: **1,195 bursts in 597.9 s on both NIFTY and BANKNIFTY** — 2.00/s, gap
p05/p50/p95 **496/501/506 ms**, a metronome not a distribution, ~4.17 tape rows per burst. The
~8 packets/s figure is an encoding artifact. Confirmed by reconciliation: DAT-15's median causal
quote age 238.7 ms + median post-print delay 258.5 ms = **497.2 ms** against a 501 ms cadence,
exactly as uniform arrival inside a fixed interval predicts.
- **`D23`'s premise is amended**: the blind window is **500 ms, not ~125 ms**. D23's structure —
  bounded, not unidentified — survives; the bound is **four times wider** than assumed.
- **`EXE-10` is harder than scoped**: a queue-position estimator on 2 Hz snapshots sees only the
  net delta across 500 ms, never the add/cancel/trade sequence inside it.
- **`EXE-09` inputs are degraded**: HLR intensities come from 500 ms-netted level deltas.
- **The touch is nearly static at this resolution**: best bid/ask *price* moves 0.24–0.67 times/s.
- Quote/Full is **not** a metronome: 1.22–1.66 updates/s, dispersed gaps. Prints and depth run on
  genuinely different clocks.
- Found by OpenClaw while verifying DAT-15, **not** by the run agent. The run agent's own solo-rate
  addendum concluded a "125–129 ms delivered view", which is wrong by 4x and wrong in the
  flattering direction; it is preserved verbatim (`2b3cdbd`) then corrected (`4f51e32`) so the
  correction is auditable.

### Decisions taken today — D25, D26, D27, all in `TASKS.md`

- **D25 — `EXE` enters the build order; a far-from-touch Kotak latency probe is authorised in
  principle.** Both **scheduled later this week, explicitly NOT today**, and the live-order step
  needs a **fresh explicit go at the time it runs** (§17.2). Driver: the maker report's Priority 0
  gates MK-01–MK-04 all require a live Kotak order path, every EXE row is Not started, and EXE was
  missing from the agreed build order entirely. EXE-09/EXE-10 move up because `MK-05` is not
  computable without them.
- **D26 — the ₹21 premium regime split is pre-registered now** as a stratification variable in
  MK-05 and MK-06, before results are inspected, per D22. Does **not** choose a regime; that stays
  with the data.
- **D27 — admissible strategy speed is bounded below by the slowest relevant feed cadence.**
  Aryan, on DAT-16: a strategy whose edge requires reacting faster than the slowest feed it
  consumes is **inadmissible by construction**. Truncates D20's empirical horizon set from below.
  Opens **`DAT-17`**: cadence is measured for depth20 only — the 5-level block inside Full and the
  whole depth200 channel are uncharacterised, and DAT-13's throttle means depth200's effective
  cadence beyond the first instrument may be far worse than nominal.

### Open, in priority order

1. **`ANL-03`** — in flight with the Opus agent. Its report is the next conversation.
2. **`DAT-17`** — needs market hours for a clean depth200 sample; the 5-level question may be
   answerable offline from retained tape.
3. **The story-by-story SIG debate** against the maker report's MK-01–MK-13, producing the D22
   claim ledger. This is still the main unstarted intellectual work.
4. **D25's EXE work** — later this week.
5. **`DAT-09`'s final strike-band and connection-count choice** — Aryan's, now computable against
   the measured 50/socket ceiling.
6. **Still open from the spread debate (Aryan, 09:53 IST):** which premium regime to target is a
   data question, not yet answered; and whether the spread level is set by his tax mechanism or by
   a fixed implied-vol spread (vega × Δσ) is **undecided** — the discriminating test needs IV/vega
   on the capture path, since premium and vega decouple only deep ITM, and that is **not yet a
   specified task**.

---

## START HERE — both commissioned agents have landed and been verified

Nothing is outstanding from the 2026-08-19 ~01:16 IST reset. Both `sig_maker_research` and
`shaurya_dat14_trade_signing` finished, and both were checked independently rather than accepted.
**The DAT-11 through DAT-16 market-hours measurements are complete and landed. The open work is the
story-by-story SIG debate and the final DAT-09 strike-band/connection-count owner choice.**

### 1. The maker research report — this is what the next conversation is for

`docs/research/sig-maker-research-2026-08-19.md` (committed to this repo 2026-08-19). 9,235 words.
Commissioned once **D21** settled that Shaurya quotes and never crosses.

**Verified 2026-08-19:** 23 of 23 peer-reviewed citations resolve correctly against Crossref with
matching author, title, venue, volume and pages — against roughly a one-in-seven error rate in the
first, taker-framed report. Every India-specific fact was checked against the primary circulars
(STT rates from 2026-04-01, transaction charges FA/73061, lot sizes FAOP/70616, the expiry-day
move, the weekly rationalisation, the 50.22% colocation share). The cost arithmetic was
re-derived by hand and reproduces. One unresolved caveat: the report claims to have corrected an
erroneous author list, but that correction is not documented in its body.

Governing conclusion, stated as an inference from market structure and not a measurement:
**presume prevailing-spread at-touch quoting in the liquid NIFTY complex has no viable edge for a
non-colocated retail-feed maker**, overturnable only by fill-conditioned, latency-realistic
evidence. Structural output is **MK-01 – MK-13**, preregistered in four tiers, with **MK-05 as an
explicit kill test** on the liquid contracts before any control-model work is justified.

It corrected an error of mine that must not propagate: STT and transaction charges are
*percentages of premium*, so they **do** scale down with option price — a ₹5 option round trip
costs ~0.24 ticks against ~0.95 ticks at ₹20. Cheap OTM options are not disqualified by tax.

**Next action: resume the story-by-story debate with Aryan.** The debate is the work; the
claim ledger (**D22**) is its output. Do not write ledger claims from the taker report alone, and
resolve each citation as its claim is reached.

### 2. The DAT-14 pre-live build — historical evidence, superseded by section 3

Pushed as `4855778` + `9f96380`; `origin/main` and local HEAD match, tree clean.

**Reproduced from scratch, not accepted:** replaying all five retained tapes through the
classifier gives exactly 21,279 rows and 12 positive-volume print intervals — 3 buy, 8 sell,
1 unclassified, 1 degraded, 5 coalesced — matching the agent's report line for line. Gates
re-run independently: 100 tests under both pytest entry points, strict mypy clean on 30 files,
ruff clean. The `1.0.0` tapes still parse under schema `1.1.0`, which the replay itself proves.

The rule is real: quote rule against the midpoint in decimal arithmetic, tick-rule fallback only
at mid, and explicit degraded `UNCLASSIFIED` for a missing, crossed or stale quote rather than a
silent forward-fill. Alignment never looks forward (`quote.state_receive_ts <= print.receive_ts`),
and a connection gap or reconnect discards the quote state instead of carrying it across.

**Three findings from the verification that the next session should carry forward:**

- **Classification requires a simultaneous depth subscription on the same instrument.** The
  alignment rule deliberately excludes the book bundled with the print itself — correct, since
  that book may already reflect the trade — so the prevailing quote can only come from the
  depth20/depth200 channels. A Quote/Full-only capture classifies nothing. That couples DAT-14
  directly to **DAT-11**'s per-socket instrument ceiling: signing trades costs depth capacity.
- **The evidence base is 12 prints from one instrument in one ~7-minute tape.** The rule is
  well unit-tested, but only the quote-rule path was exercised against real data; the tick-rule
  fallback has never fired outside tests. Treat the dry-run level as genuinely thin.
- **Early coalescing numbers, anecdote not measurement (n=12):** the signed last print covers
  only **63%** of traded volume — 2,210 of 3,510 units — so 37% carries no attributable sign.
  Quote ages at classification ran 58–427 ms against the 1 s freshness bound. Both numbers are
  exactly what **DAT-15** exists to measure properly.

### 3. DAT-11 through DAT-16 market-hours outcomes — landed

- **DAT-11:** exact observed 20-level one-message ceiling is **50**. Fresh 50 worked; 51, 52,
  and 53 failed wholesale. This corrects the prior-day statement that 52 worked. A later
  fresh-socket solo addendum delivered 116, 120, 114, and 114 NIFTY rows/15 s versus 116 inside
  the 50-instrument run. That rules out shared-socket bandwidth collapse but is **not
  discriminating** for cap versus event rate because one publication contains multiple rows.
- **DAT-16 correction:** timestamp grouping identifies the 20-level channel as a fixed **2.00
  snapshot bursts/s** feed with ~4.17 rows/burst and a **500 ms** D23 netting bound. The ~8 rows/s
  figure is an encoding artifact, neither a packet cap nor a true event rate.
- **DAT-12:** **socket-scoped** at the reproduced 50+50 load. Message two failed on the loaded
  socket and succeeded unchanged on a fresh socket. A 2+2 control accepted both messages, so the
  effect is load-dependent rather than a universal first-message-only rule.
- **DAT-13:** the 200-level skew is a real first-subscription throttle/bias. NIFTY-first and
  BANKNIFTY-first rotations both produced 328 packets for the first future and 2 for every later
  future.
- **DAT-14:** Live verified for two front-month futures/depth20/one 10-minute morning window:
  313 prints, 158 buy/154 sell/1 unclassified, 1 real tick-rule fallback, 1 degraded, 113
  coalesced, and 313/313 version stamps.
- **DAT-15:** Live verified for the retained eight-tape sample (38,572 rows, 482 prints), with a
  healthy-core quote-age median/p95 of 238.7/462.6 ms and 5/320 post-BBO proxy flips. The
  simultaneous depth20/depth200 capture was reconnect-heavy; its cross-tier comparison is a
  stress diagnostic, not a general tier ranking. Options, midday, and a healthy depth200-aligned
  run remain unmeasured.

Canonical details, denominators, identification limits and residual gaps are in `TASKS.md`,
`docs/module-spec/DAT.md`, and `docs/live-evidence/DAT-11-2026-08-19.md` through
`DAT-15-2026-08-19.md`.

## Mandatory restart context

1. Load and follow `OPENCLAW_WORKING_INSTRUCTIONS_REVISED.md` for the new session.
2. Read `README.md` and the entire `TASKS.md` before discussing or changing scope.
3. Treat D1–D24 and the frozen 13-component list as binding. Do not reopen settled design
   choices merely because a different implementation would be easier.
4. Before editing the repository, `git fetch` and compare `HEAD` against `origin/main` — more
   than one process has committed to this clone concurrently before.
5. **Current state as of 2026-08-19 ~10:52 IST**, superseding the 2026-08-17 line that said no
   code had been harvested: real code exists and is pushed. CON contracts, INF packaging, the
   DAT component through DAT-16, and the SUR eSSVI surface stack are implemented, with 107 tests,
   strict mypy clean on 31 package files plus live-analysis scripts, and Ruff clean. Per-component
   specs live in `docs/module-spec/*.md`; `MODULE_SPEC.md` is the index over them.
6. **Market-hours work DAT-11 through DAT-16 completed on 2026-08-19.** Read the dated evidence
   under `docs/live-evidence/` before using the 50-instrument ceiling, socket-scoped reconnect
   result, 200-level throttle, trade-signing evidence, or alignment-error estimates.

## SIG discussion — round 1 held 2026-08-19; both commissioned reports have landed

Held on Telegram ~00:05–00:25 IST. Three framing questions were put: sampling clock, pooling
coordinate, and prediction-horizon set. Aryan's answer to all three was the same — **we do not
know, and only the data can tell us** — recorded as **D20** in `TASKS.md` and written into
`docs/module-spec/SIG.md` under "Measurement design is empirical". All three become swept axes in
`SIG-19`'s trial log and are counted in `SIG-12`'s grid.

**Aryan's instruction, binding on the next session:** no further SIG design decision is taken
until a commissioned literature review lands. A single `sessions_spawn` research agent
(`sig_feature_research`) was started 2026-08-19 ~00:22 IST once the DAT and SUR builds finished,
briefed to survey what actually moves NSE index futures and options — weighted heavily toward
Indian market structure, organised by horizon, reading across viewpoints rather than one school,
and for each candidate story stating what the data would have to show for it to be true and what
would falsify it. Aryan's own worked example of the shape: options can be traded through
volatility arbitrage, or by predicting the forward and hence the option's fair value some seconds
ahead — which of those is real is a data question, not a modelling preference.

**Both reports are now in and verified — see START HERE section 1.** The taker report
(`docs/research/sig-feature-research-2026-08-19.md`) carries four inline corrections and a standing
citation-reliability warning; the maker report supersedes its framing under **D21**. Resume the
story-by-story debate from the maker report. Do not re-derive `SIG-01`–`SIG-20`; this is
sharpening and narrowing, not redesign.

## Queued debate — resolved, see D19

Added 2026-08-18 ~16:23 IST from Aryan's voice-captured thought, debated live on Telegram the
same evening, and closed as **D19** in `TASKS.md`'s decisions log. Asked directly whether "live"
meant a dashboard on `SUR`'s existing fit/smoothing cadence, or a hard latency requirement on the
fit itself feeding quoting. Aryan: **"It's only about watching, no worries."** `ANL-03` already
covers this (it harvests Market Making's `monday_v1/surface_dashboard.py`/`surface_server.py`);
no new task, no change to `SUR`'s Python-only research-fit scope. See D19 for the full record.

## Do not re-ask settled questions

Aryan has already answered the substance of the five questions previously drafted here. The
documents are the answers:

1. `MODULE_SPEC.md` guarantees come from D1–D15, the full stable-ID task ledger, and the canonical
   working contract. Do not ask Aryan to restate them.
2. Contract semantics are already specified by CON-01–CON-09 plus the timing, identification,
   proxy, risk, replay, and artifact decisions throughout D7–D15.
3. There is no owner choice between a research, paper, or live "MVP". The full frozen module is
   required; evidence levels may rise component by component, but internal sequencing never
   rewrites completion scope.
4. D5/MIG-01 already require Market Making to consume Shaurya. MIG-02 recommends VOLARB as the
   first broader migration, while O5 is deliberately deferred until each old strategy is touched.
5. D12 already decided that the raw tape is recorded. DAT-09 asks only how much, and explicitly
   waits for measured packet rates and capacity before Aryan makes that sizing choice.

At session start, do not interview Aryan. Convert the recorded decisions into formal artifacts and
work. Ask only if implementation exposes a genuinely new meaning-changing choice not answered by
the ledger.

## First five actions on return — ALL COMPLETED, retained as history

These were written on 2026-08-17 and are done: `MODULE_SPEC.md` and the per-component specs in
`docs/module-spec/` exist, the traceability ledger is `TASKS.md`, and the DAT-01/02 read-only
bootstrap is live-verified. Do not re-run them. The live work is START HERE section 3.

1. **Decision-completeness audit.** Map D1–D15 and every non-dropped task into a requirement
   inventory; identify contradictions or genuinely missing meanings without asking Aryan to repeat
   settled answers.
2. **Draft `MODULE_SPEC.md`.** Formalise objective, object/identification ledger, architecture,
   contracts, component requirements, timing/causality, safety gates, outputs, robustness,
   acceptance tests, exclusions, deferred items, and completion criteria using stable IDs.
3. **Create requirements traceability and artifact contracts.** Every frozen task gets a row with
   code/test/output targets; define schemas and semantic invariants for required artifacts before
   implementation.
4. **Write the implementation plan.** Resolve dependency order, harvesting sources, engineering
   work packages, parity gates, and end-to-end acceptance checkpoints. Internal phases must retain
   the full external completion requirement.
5. **Prepare the forward-only data bootstrap.** Specify and, where prerequisites permit, implement
   the read-only DAT-01/02 measurement path needed to observe packet rates, concurrent capacity,
   and storage load. Present evidence before returning DAT-09 to Aryan for a sizing decision.

## Engineering calls already delegated to OpenClaw

Do **not** ask Aryan to decide these unless an implementation constraint would change model
meaning, risk, outputs, or the frozen scope.

### Repository and packaging architecture

- One standalone monorepo with root `contracts/`, `python/`, `native/`, `docs/`, and CI tooling.
- `python/` builds an installable `shaurya` distribution with an explicit plugin registry.
- `native/` builds and exports a consumable CMake target in namespace `shaurya::`.
- Contracts are versioned artifacts consumed by both languages; strategies pin Shaurya releases.
- CI enforces tests, format/lint/type/build gates, Python↔C++ parity where relevant, and the
  one-way dependency rule: Shaurya never imports from a strategy.
- Semantic versioning and a changelog begin with the first implementation commit.

### Implementation sequence and first acceptance chain

1. Write and freeze `MODULE_SPEC.md` with stable requirement IDs and a traceability matrix.
2. Build CON contracts first, with INF packaging/build/test/security foundations alongside them.
3. Start DAT-01/02/06/07 early because tick collection is forward-only; use a measured live
   session to resolve DAT-09 rather than assumptions.
4. The first internal end-to-end acceptance chain is:
   broker event -> canonical tape -> deterministic replay -> strategy interface -> C++ paper
   broker/risk gate -> canonical ledger -> read-only analytics.
5. This internal chain is a sequencing device, not an MVP or scope reduction. All frozen
   components remain required.
6. Harvest, reconcile, test, and generalise existing code; do not rewrite working components from
   zero without evidence that harvesting is infeasible.
7. No live-order path is enabled merely because the chain passes. Live readiness remains gated by
   the full EXE/RSK/NAT requirements and explicit per-session human authorisation.

## After the first five actions

Report the decision-completeness audit and draft artifacts plainly. Raise only genuine unresolved
choices. Then hold the open idea-browsing session; any new capability becomes a new stable task ID
and does not silently widen an existing task.
