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

## Method

**`METHOD.md` is binding on all of SIG**, not just this ledger. It defines the claim →
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
