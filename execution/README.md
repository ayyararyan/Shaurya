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

The release-gate entrypoint is `scripts/validate_integration.sh`. It requires an empty build
directory under `/private/tmp`, accepts explicit CMake/CTest/Python executables through
`CMAKE_BIN`, `CTEST_BIN`, and `PYTHON_BIN`, and can run the two-repository audit with
`--d51-root`. It never installs dependencies or contacts a broker, AWS, SSH, or the public network.

The parity harness is built as `shaurya-parity-harness`. Its `version` command attests the exact
source commit and contract digests; `run --fixture ... --output ...` replays one manifested fixture
and writes only to the caller-selected output path. Ledger verification and evidence-preserving
repair behavior are documented in `docs/LEDGER_AND_RECOVERY.md`.

Safe operator entrypoints are `kotak help`, `kotak version`, `kotak doctor`, and the explicitly
confirmed `kotak shaurya-shadow-launch --confirm SHAURYA_SHADOW_LAUNCH`. See
`docs/SHADOW_OPERATIONS.md`; no command in this release enables live order routing.

Configuring with `SHAURYA_ENABLE_LIVE_ROUTER=ON` is intentionally a fatal error. See
`EXECUTION_CONTROL_PLANE_SPEC.md`, `docs/SHADOW_SAFETY.md`, and
`docs/LIVE_ENABLEMENT_CHECKLIST.md`.
