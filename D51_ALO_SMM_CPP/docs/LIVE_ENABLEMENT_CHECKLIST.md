# Live enablement checklist — NOT for the shadow month

The source contains a real Kotak place/modify/cancel router and an order-update parser, but the distributed/default build has the live compile gate **OFF** and refuses live execution. Do not enable it merely because shadow P&L looks positive.

Before any later live pilot:

- [ ] Several weeks of independent shadow days are analyzed walk-forward and the retained action statistics pass the month-end tests.
- [ ] Current Kotak endpoints, headers, rate limits, static-IP rules, lot sizes, ticks and statutory charges are re-verified.
- [ ] A real-account order-update capture is contract-tested against the included parser.
- [ ] Place/modify/cancel acknowledgements, partial fills, rejects and cancel/replace races are reconciled against broker order/trade reports and contract notes.
- [ ] **Automatic startup broker-position reconciliation is implemented**; the engine fails closed if broker and local inventory disagree.
- [ ] Before every SELL, broker-confirmed available inventory is sufficient for the exact option token.
- [ ] End-of-day live inventory policy is chosen and tested.
- [ ] Network/session loss and order-stream loss have a tested freeze/cancel policy.
- [ ] Daily loss, max drawdown, max gross premium, max inventory/Greeks and stale-feed hard kills are implemented for live capital.
- [ ] One-lot non-strategy API harness is tested first, followed by one-lot strategy pilot.
- [ ] Only regular LIMIT orders are used by D51.

The included order-update path already reconciles incremental filled quantity into token-level inventory and fails closed on unknown instruments or a long-only violation. That is **not** equivalent to real-account validation and is intentionally insufficient for live enablement by itself.

Only after completing the checklist should you deliberately rebuild:

```bash
cmake -S . -B build-live -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DALO_ENABLE_LIVE_ROUTER=ON
cmake --build build-live
```

Even that binary still requires `mode=live`, the exact `ALO_LIVE_ACK`, and `ALO_LIVE_START_FLAT_ACK=I_CONFIRM_ACCOUNT_FLAT`. The flat acknowledgement is only an explicit operator attestation; it is **not** a substitute for automatic broker-position reconciliation.
