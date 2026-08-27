# research/docs — index

This folder holds the research programme's documentation: specifications, evidence logs,
result artifacts, and background research. `research/docs/README.md` is the index; it does
not contain findings itself.

## Subdirectories

| Directory | What belongs here |
|---|---|
| [`module-spec/`](module-spec/) | One file per module taxonomy cell (`ANL`, `BKT`, `CON`, `GRK`, `INF`, `MIG`, `NAT`, `RSK`, `SIG`, `SUR`, `VOL`) — the standing definition of what each module owns. |
| [`sig-claims/`](sig-claims/) | The pre-registered `SIG` hypothesis ledger: claim files, `H-*` registration bodies and their dated amendments, and the binding `METHOD.md`. |
| [`results/`](results/) | Result artifacts (JSON/CSV) and their accompanying report/spec documents for completed studies — anything whose primary content is "here is what the data showed." |
| [`live-evidence/`](live-evidence/) | Dated exploratory-scan write-ups and live/intraday execution documents — frozen protocol specs, amendments, and analysis logs tied to a specific tape or live monitoring run (`DAT-*`, `ANL-*`, `SIG-21-*`, `OFI-*`, `CKS-*`, `DEEPBOOK-*`). |
| [`research/`](research/) | Literature review and background research, not tied to a specific execution or dataset. |
| [`specs/`](specs/) | Pipeline/tooling specs (e.g. test layout, the post-market research pipeline) — infrastructure, not a market-behaviour study. |
| [`legacy/`](legacy/) | Superseded or closed documents: retired specs whose reports and traceability matrices already live here, changelog, old module spec, task lists, and session handoff notes. |

## Top-level documents

These remain at the top level because they are current, live reference material — not tied
to one closed study.

| File | Purpose |
|---|---|
| [`CONTRACTS.md`](CONTRACTS.md) | Live interface/data contracts referenced across modules. |
| [`SURFACES.md`](SURFACES.md) | Live reference for the options/futures surface objects. |
| [`SIG-21-CALIBRATION-RUNBOOK.md`](SIG-21-CALIBRATION-RUNBOOK.md) | Operating runbook for `SIG-21` calibration; standing procedure, not a dated result. |
| [`SURFACE-MISPRICING-SPEC-2026-08-20.md`](SURFACE-MISPRICING-SPEC-2026-08-20.md) | Live surface-mispricing specification (its internal "superseded" notes are its own amendment history, not a retraction of the spec). |
| [`D39-FIXED-TARGET-PANEL-SPEC-2026-08-21.md`](D39-FIXED-TARGET-PANEL-SPEC-2026-08-21.md) | Live fixed-target panel spec (`D39`); still open. |
| [`D49-C8-RESPONSE-SURFACE-SPEC-2026-08-21.md`](D49-C8-RESPONSE-SURFACE-SPEC-2026-08-21.md) | Live `D49`/`C8` response-surface spec; its result report already lives in `results/`. |
| [`D51-10S-FEATURE-SELECTION-SPEC-2026-08-21.md`](D51-10S-FEATURE-SELECTION-SPEC-2026-08-21.md) | Live `D51` 10-second feature-selection spec; its result artifacts already live in `results/`. |

## Archive

Closed and superseded studies were filed into the directories above rather than deleted.
Notable groupings:

- **`legacy/`** — `CCZ-OFI-MIGRATION-SPEC` + `TRACEABILITY` (alongside the existing
  `CCZ-MIGRATION-REPORT.md`), `TOUCH-METRICS-SPEC` (alongside the existing
  `TOUCH-METRICS-REPORT.md`), and the `NEXT-SESSION-PROMPT` session handoff note.
- **`results/`** — the `D40`, `D41`, and `D50` spec+report pairs (each colocated with its
  existing JSON result), the `OFI-HORSERACE` spec/coverage/report set, the
  `OFI-PREDICTIVE-SCAN` spec/report set, and the `SURFACE-FUTURES-PREDICTIVE`
  spec/coverage/correction/report family.
- **`live-evidence/`** — the `CKS-L1-OFI` spec/amendment/report set, `DEEPBOOK-NORMAL-ACTIVITY`,
  `OFI-LATE-PARTIAL-EXPLORATORY-SPEC`, `OFI-FULL-SESSION-REPLICATION-SPEC` + amendment, the
  `OFI-DASHBOARD` spec and its four amendments, `D38-D39-D40-LIVE-AMENDMENT`, and
  `SIG-21-CONSTRUCTION-REPLAY` / `SIG-21-EXPLORATORY-RESPONSE` (siblings of the existing
  `SIG-21-CONSTRUCTION` and `SIG-21-PIPELINE` evidence files).
