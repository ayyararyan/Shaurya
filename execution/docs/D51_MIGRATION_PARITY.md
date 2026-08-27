# D51 Migration and Parity

D51 retains strategy selection, surface fitting, models, policy, and research outputs. Shaurya owns
canonical execution contracts, routing, risk, order lifecycle, PaperBroker fills, reconciliation,
IPC authority, and the durable execution ledger. D51's adapter carries the observation's canonical
instrument and routing provenance into integer-paise, exchange-unit neutral intents; broker token,
symbol, credentials, floating prices, Greeks, and model scores never cross that boundary.

Verified on 2026-08-27:

- D51 commit: `2abcb5d7fa5481c0b44d1d3b7ef03c94340bf1e2`
- Shaurya parity commit: `e9c92750c10c013250de76ee6f76140a86e718ed`
- fixture manifest: `484c717903b82df5f36298aa2763c18e69387028a552d7aa2bc0c5da3aa12c21`
- client contract: `f3cda8ece922cc43b177ec3680dc355a742e93abe535609ea3326890274f266c`
- schema: `4522b0000f50844e9ad5b8570f730ef7e1988295eee02e2983d059e476f36f98`
- PaperBroker models: `d51_proxy_v1`, `scripted_v1`
- result: 17 scenarios, zero semantic mismatches, no waiver or approved semantic difference.

The comparator excludes only harness build hash and source commit; action, canonical instrument,
price, quantity, event sequence, fill evidence, inventory, incidents, and terminal state remain
semantic. Both Debug and Release D51 suites parsed a valid machine-readable result bound to the
exact D51 commit. `shaurya` is the checked-in shadow default. `--legacy-execution` is an explicit
stopped-session rollback and remains live-disabled.
