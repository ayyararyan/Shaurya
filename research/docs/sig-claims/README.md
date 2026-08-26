# SIG claim ledger (D22)

The pre-registered hypothesis set. `SIG-19`'s trial log is checked against this: anything
tested must appear here **first**, and any addition is recorded **before** results are
inspected. Literature seeds claims; it does not settle them (D22, Aryan's qualification).

## ID scheme

One file per `SIG-01` taxonomy cell. Claim IDs are `<CELL>-nn`, stable and never reused.

| Cell | Prefix | File | SIG task |
|---|---|---|---|
| Book state (static) | `BK` | [`book-state.md`](book-state.md) | SIG-02 |
| Event flow | `EF` | [`event-flow.md`](event-flow.md) | SIG-03 |
| Price-path derived | `PP` | `price-path.md` | SIG-04 |
| Cross-asset | `XA` | `cross-asset.md` | SIG-05 |
| Options-specific | `OP` | `options.md` | SIG-06 |
| Time and regime | `TR` | `time-regime.md` | SIG-16 |

These are distinct from the maker report's `MK-01`–`MK-13` agenda, which are *programme
gates* (instrumentation, labels, kill tests). A gate says "measure this before anything is
justified"; a claim says "this proposition is true or false about the market". Claims cite
the gates they depend on.

## Registered execution hypotheses and their amendments

`H-*` files are execution registrations: a complete, frozen test protocol committed and pushed
*before* outcomes are inspected, with the pushed commit acting as the registration clock.

| Registration | File | Registering commit | Status |
|---|---|---|---|
| `H-SIG21` — deep-book anomaly to later NIFTY-futures price response | [`H-SIG21.md`](H-SIG21.md) | `f2cf650`, pushed 2026-08-19T15:00:42+05:30 | Active; outcome gate closed |

**A registration body is never edited.** Editing it in place would make the file and its
registration clock disagree and would destroy the audit trail. Meaning-changing alterations are
recorded as dated, numbered amendment files beside it and listed here.

| Amendment | Amends | Approved | Pre-data? | Summary |
|---|---|---|---|---|
| [`H-SIG21-A1.md`](H-SIG21-A1.md) (`D34`) | `H-SIG21` §6 | Aryan, 2026-08-19 ~17:40 IST | **Yes** — zero of the 25 required post-registration sessions collected | The primary non-overlapping episode window is bound to each cell's own `Z + h2` instead of the 11 s family maximum. The family-maximum window is retained as a declared robustness arm. The matched-quiet-control definition is deliberately **not** changed and remains open. |
| [`H-SIG21-A2.md`](H-SIG21-A2.md) | `H-SIG21` full-session calendar and derived ceilings | Official dated-calendar correction, 2026-08-19 | **Yes** — zero of the 25 required post-registration sessions collected | The NSE F&O close is date-versioned: 15:30 before 2026-08-03 and 15:40 from that date. A current session is 23,100 seconds, giving 11-second ceilings of 2,100 / 10,500 / 42,000. Registered 30-minute bins retain a short 15:30–15:40 final bin. |

## Method

**`METHOD.md` is binding on all of SIG under `D29`**, not just this ledger. It defines the claim →
hypothesis → trial-log chain, the eight measurement axes every hypothesis must bind, the
mandatory resolution statement, ex-ante power requirements, the verdict vocabulary, and
pre-registration by commit order. Read it before adding or testing anything.

## Required fields per claim

Per D22, every claim records: **mechanism** (why it would move prices, not that it
correlates), **resolved citations**, **capture path** from our own feed, **confirming
test**, **falsifying test**, and **`CON-06` identification status**.

## Status vocabulary

`Proposed` (drafted, not yet debated with Aryan) → `Agreed` (debated and accepted into the
pre-registered set) → `Tested` (a `SIG-19` trial log entry exists) → `Confirmed` /
`Falsified` / `Inconclusive`. A claim is never deleted; it is falsified and kept.
