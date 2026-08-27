# Verification Report — 2026-08-27

## Verified outcomes

- Shaurya starting commit: `bcb6dea02329f824c82488f29450af0dd0e826ca`.
- Frozen Shaurya parity harness commit: `e9c92750c10c013250de76ee6f76140a86e718ed`.
- Clean Shaurya Release build with warnings-as-errors: 38/38 CTests passed before delivery docs.
- D51 final verified commit: `2abcb5d7fa5481c0b44d1d3b7ef03c94340bf1e2`.
- Clean D51 Debug: 9/9 CTests. Clean D51 Release: 9/9 CTests.
- Both D51 parity reports were parsed as JSON and recorded 17 scenarios, zero mismatches, exact
  D51/Shaurya commits, protocol/schema/fixture digests, and both PaperBroker models.
- D51 preparation tests: 4/4. Broker tests: 18 run, 16 passed and 2 platform-skipped. Watcher
  tests: 18 run, 16 passed and 2 platform-skipped. Composite legacy launch suite passed.
- Package manifest verification passed. Repository audit passed with empty committed and working
  diffs for `data/` and `research/` in the isolated Shaurya worktree.
- Protected Data regression validation passed: 113/113 pytest tests, repository Ruff, and strict
  mypy over 25 source files. Protected Research regression validation passed: 703/703 pytest tests
  (242 known numerical warnings), configured strict mypy over 55 source files, and the documented
  Research/CLI source scope passed Ruff. The auxiliary repository-wide Research Ruff invocation
  reproduced the already-recorded baseline of 577 findings under the unrelated protected
  `scratch/` tree; no Data or Research file was edited to alter that baseline.
- The portable CTest exercises two independent temporary homes/prefixes, byte-identical archives
  and manifests, update, rollback, recovery, scoped uninstall, foreign-file preservation, traversal,
  symlink, mode, ownership, and concurrent-operation refusals.
- Shaurya and D51 live-enabled CMake attempts are required to fail before transport construction.

## Commands

The final combined gate is:

```sh
CMAKE_BIN=/absolute/path/to/cmake CTEST_BIN=/absolute/path/to/ctest \
PYTHON_BIN=/absolute/path/to/python3 SHAURYA_ROUTING_TEST_PYTHON=/absolute/path/to/python3 \
execution/scripts/validate_integration.sh \
  --build-dir /private/tmp/shaurya-execution-build \
  --d51-root /path/to/clean/d51-worktree \
  --summary /private/tmp/shaurya-integration-summary.json
```

The concrete build, protected Data/Research checks, two-repository audit, final branch push, and
remote-head comparison are performed after this report-containing commit. Their exact immutable
object IDs are reported in the delivery response because a Git commit cannot contain its own hash.

## Skips and external boundaries

Two D51 operational cases are platform-skipped on macOS: Linux inotify and Linux
`SOCK_SEQPACKET`. Equivalent C++ IPC behavior is covered by the macOS stream transport and Shaurya
E2E suite. Research emitted 242 existing numerical-runtime warnings during its passing suite; the
repository-wide Research Ruff baseline is recorded above rather than waived or modified. No real
broker authentication, order, AWS/service mutation, SSH connection, system or real-home install,
or public-network test occurred. All live-enablement items remain open in
`LIVE_ENABLEMENT_CHECKLIST.md`; this release is not live-ready.
