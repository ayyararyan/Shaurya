# Shaurya Changelog

Shaurya uses semantic versioning. Each release records the implementation evidence relevant
to strategies that pin the package.

## Unreleased

### SUR-01, SUR-02, SUR-05, SUR-06, SUR-07, and SUR-08 — eSSVI surfaces

- Added one module-facing surface interface over CON-01 tape input and CON-03 frame output.
- Added synchronized multi-expiry eSSVI calibration with butterfly and calendar constraints,
  independent arbitrage checks, weighted fit/residual/stability diagnostics, and explicit
  strike/maturity support policy.
- Added arbitrage-rechecked temporal smoothing, caller-supplied staleness thresholds, and a
  fail-closed gate that prevents raw tick-synchronous fits from serving quoting consumers.
- Dry-run acceptance uses realistic synthetic option BBOs; live/historical DAT replay
  integration remains pending and is not represented as live verified.

## v0.1.0 — 2026-08-18

The first release is `0.1.0`: Shaurya is already an installable dependency with live-verified
market-data foundations and tested contracts, but the frozen module is intentionally still
pre-`1.0.0` while most domain components and the native package remain unimplemented.

### DAT-01, DAT-02, and DAT-05-lite — initial Python distribution

- Built the installable `shaurya` package and reconciled the Mushin Gamma and Shoshin Dhan
  clients into one data-only client.
- Added supervised standard, 20-level, and 200-level WebSocket capture, versioned tape and
  instrument contracts, reconnect/resubscribe, heartbeat, sequence-gap semantics,
  permission-restricted manifests, and append-only JSONL output.
- The first accepted 20-level run recorded 232 packets in 30.001 seconds with zero reconnects;
  the later combined standard-plus-20-level run recorded 419 packets in 45 seconds with both
  required channels present.

### DAT-10 — 200-level deep-book capture

- Generalised the deep-book parser and added the 200-level endpoint and subscription shape.
- Corrected a silent zero-packet failure by using the endpoint's flat subscription message
  rather than the 20-level batch envelope; added a regression test.
- Live run `sha-20260818T092355.175225Z-d181b3ff` recorded 366 packets in 45.001 seconds and
  independently verified 200 bid plus 200 ask levels in the tape.

### MODULE_SPEC — frozen-requirement draft set

- Added the root `MODULE_SPEC.md` and 13 component specifications under `docs/module-spec/`.
- Mapped all 107 non-dropped task IDs exactly once to stable `REQ-*` rows with code, test, and
  output targets.

### CON-02, CON-03, CON-04, CON-06, CON-07, and CON-09 — shared contracts

- Added six strict, versioned Pydantic contracts, shared object-category and IST-causality
  types, and four committed cross-language JSON fixtures.
- Contract acceptance at implementation time was 52/52 pytest tests, strict mypy over 18
  source files, and a repository-wide Ruff pass.

### INF-02, INF-05, INF-07, and INF-09 — package and release foundation

- Reconciled the existing package metadata against VOLARB and Shoshin, retained the stricter
  setuptools/strict-mypy/Ruff configuration, and verified a clean editable install.
- Added the external-handle/700/600 secret policy and hardened ignore rules for credentials,
  runtime state, logs, and generated data.
- Established this changelog and the matching `v0.1.0` package/release version.
