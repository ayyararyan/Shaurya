# Shaurya Execution

Shaurya Execution is the broker-neutral order control plane. It owns routing, deterministic risk,
idempotency, order lifecycle, reconciliation, and the append-only execution ledger. Ordinary builds
are shadow-only and contain no live broker transport.

## Build and test

Use an out-of-tree build directory:

```bash
cmake -S execution -B /private/tmp/shaurya-execution-build \
  -DCMAKE_BUILD_TYPE=Release -DSHAURYA_ENABLE_LIVE_ROUTER=OFF
cmake --build /private/tmp/shaurya-execution-build --parallel
ctest --test-dir /private/tmp/shaurya-execution-build --output-on-failure
```

Configuring with `SHAURYA_ENABLE_LIVE_ROUTER=ON` is intentionally a fatal error. See
`EXECUTION_CONTROL_PLANE_SPEC.md`, `docs/SHADOW_SAFETY.md`, and
`docs/LIVE_ENABLEMENT_CHECKLIST.md`.
