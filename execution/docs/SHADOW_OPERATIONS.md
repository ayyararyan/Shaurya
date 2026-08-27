# Shadow Operations

This procedure is for shadow evidence only. No Kotak credential is required and no broker order is
placed, modified, or cancelled.

1. Verify the installed release with `kotak version` and offline `kotak doctor`.
2. Run the bounded read-only `kotak doctor --remote` only when the operator intends to check the
   configured host. Any host-key, build, source-tree, helper, unit, or live-gate mismatch is terminal.
3. Create a checksum-bound request with `kotak prepare --confirm SHAURYA_PREPARE`.
4. Run `kotak preflight` and inspect the non-secret marker.
5. Launch with `kotak shaurya-shadow-launch --confirm SHAURYA_SHADOW_LAUNCH`. The compatibility alias
   `kotak shadow-launch --confirm SHAURYA_SHADOW_LAUNCH` has identical shadow-only semantics.
6. Treat readiness as established only after peer identity, routing, ledger replay, exact paper
   reconciliation, a fresh observed book, and durable `session_started` evidence agree.
7. Use `kotak status` for factual state. Do not infer success from process existence alone.
8. On queue overflow, IPC loss, ambiguous submission, ledger fault, projection disagreement, or
   stale authority, stop new intents and preserve the incident/ledger evidence for reconciliation.
9. Shutdown revokes authority first, attempts bounded factual cancels, flushes the ledger, and marks
   the terminal state uncertain unless every working order and reconciliation query agrees.

Rollback is a new stopped D51 session selected with `--legacy-execution`. End and reconcile the
Shaurya session first. Rollback does not rewrite the Shaurya ledger, reuse the session ID, migrate
open orders, or enable live routing. The legacy route is temporary authenticated feed-only research
support and has its own explicit confirmation marker.
