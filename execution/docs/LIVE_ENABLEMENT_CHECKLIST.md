# Live Enablement Checklist

This shadow branch cannot satisfy or waive any item below. Every item requires a separate live
build, evidence review, and explicit operator authorization.

- [ ] Verify current Kotak endpoints, headers, rate limits, static-IP rules, and authentication.
- [ ] Capture and fixture-test the real-account order-update contract.
- [ ] Verify place, modify, cancel, and cancel-race reconciliation.
- [ ] Prove automatic startup order, trade, and position reconciliation against broker authority.
- [ ] Verify exact-token SELL availability.
- [ ] Approve the end-of-day inventory policy.
- [ ] Verify network and order-stream loss handling.
- [ ] Approve and test hard daily loss, drawdown, exposure, inventory, and Greek kills.
- [ ] Complete a separately authorized one-lot non-strategy harness.
- [ ] Complete contract-note reconciliation.
- [ ] Approve a separate live build/release process and explicit operator authorization.
