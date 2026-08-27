# Section 06 — Portable `kotak` Operator CLI and Release Lifecycle

## Outcome and boundaries

This section makes the canonical `kotak` operator control plane distributable across Macs without
embedding a personal path, credential, host secret, D51-specific service name, or mutable runtime
state in either repository. It provides offline inspection, explicit remote operations, one-shot
shadow launch, non-secret audit identity, reproducible packaging, safe installation/update/rollback,
and manifest-scoped removal.

The CLI is an operator control plane used once per execution session; it is never called per order.
The new `shaurya-shadow-launch` path does not authenticate to Kotak because the shadow executor uses
Dhan observations and a paper broker. `auth` remains a separate explicit diagnostic command. During
this implementation every SSH, broker, watcher, and service interaction is exercised only through
hermetic fixtures. Do not contact a real host, authenticate, prompt for a real TOTP, start or stop an
AWS service, alter cloud infrastructure, provision SSH identity, or install into the real home.

The section depends on the executor command, readiness markers, launch-attestation contract, and
runtime topology being frozen. It creates only files under `execution/ops/`, `execution/tests/ops/`,
and related documentation paths; it does not modify Data or Research.

## Tests first

Create hermetic tests before porting operational behavior. Tests must replace SSH, terminal input,
clock, hashing, and remote helpers with explicit fixtures. A guard must fail the suite if a real
network executable, real home installation prefix, broker endpoint, or service manager is reached.

### Command parsing and no-network tests

Create `execution/tests/ops/test_kotak_cli.sh` and a recording SSH fixture under
`execution/tests/ops/fixtures/bin/`. Cover:

- `kotak help`, `--help`, `version`, and `doctor` entirely offline;
- `doctor --remote` making exactly one bounded read-only SSH fixture invocation;
- `auth`, `status`, `prepare`, `preflight`, `shaurya-shadow-launch`, and the `shadow-launch` alias;
- `--dry-run` for every relevant command;
- unknown or multiple commands, duplicate flags, missing values, extra positional arguments,
  malformed manifest, missing confirmation, and wrong confirmation;
- help/version/dry-run/malformed/missing-confirmation paths creating no locks, logs, state, prompts,
  or SSH records;
- strict-host options, non-PTY batch transport, forwarding refusal, one connection attempt, connect
  timeout, server-alive bounds, and no password/keyboard-interactive fallback;
- exit codes and exact marker grammar for success, refusal, failure, timeout, and unverified result;
- `shaurya-shadow-launch --confirm SHAURYA_SHADOW_LAUNCH` and `shadow-launch` producing identical
  plans, transport records, markers, and exit codes.

Freeze exit classes: `0` success, `2` usage/refusal before work, `3` verified remote refusal,
`4` bounded timeout, `5` terminal result unavailable, and `70` internal integrity failure. Markers
must be single-line ASCII key/value records from a closed allowlist; do not print paths containing
usernames, instrument identities, payloads, remote response bodies, or secret-bearing values.

### Doctor and manifest tests

Create `execution/tests/ops/test_doctor.sh` and canonical fixtures under
`execution/tests/ops/fixtures/manifests/`. Verify that offline `doctor` checks, without changing
state:

- CLI/release version, release-manifest digest, installed file hashes and modes;
- deployment-manifest schema/digest and executor compatibility version;
- required local commands and supported macOS architecture;
- state/config directory ownership and permissions if they already exist;
- operator/device configuration and non-secret public-key fingerprint syntax;
- absence of personal absolute paths and unsafe writable installation parents.

`doctor --remote` must run one fixed read-only compatibility helper through one SSH process. The
helper may report OS/architecture, installed executor commit/build digest, deployment digest,
expected unit names and inactive/active status, live gate OFF, helper hashes, and protocol versions.
It must not read a credential file, run broker authentication, start/stop/enable a unit, write a
file, or accept a manifest-provided shell fragment. Test timeout, malformed response, extra fields,
wrong executor, wrong live gate, host-key refusal, and a second attempted SSH invocation.

Reject manifests containing unknown/missing/duplicate fields, invalid Unicode/JSON, traversal,
relative protected paths, unbounded strings, duplicate installed paths, absolute local user paths,
shell metacharacter command fields, mismatched hashes, or unsupported versions.

### TOTP and secret non-disclosure tests

Port the useful D51 hidden-prompt and transport tests into
`execution/tests/ops/test_auth_transport.py` or an equivalent PTY harness. Use a synthetic six-digit
value only. Assert that:

- `auth --confirm KOTAK_AUTH` prompts through a controlling terminal with echo disabled;
- the value travels only on the fixed helper’s standard input, never argv, environment, file, log,
  shell history, marker, exception, or process listing fixture;
- invalid format, EOF, interruption, helper/hash mismatch, authentication refusal, timeout, and
  result-transport failure clear in-memory buffers and return factual markers;
- command tracing and diagnostic dumps cannot reveal the value;
- stable broker credentials remain remote and are referenced only by a fixed protected path inside
  the remote helper, never read by local code or tests.

The new shadow launch must neither prompt for TOTP nor invoke the authentication helper.

### One-shot launch and session-broker tests

Port and generalize the existing D51 broker, watcher, and shadow-launch suites under
`execution/tests/ops/`. Cover single-consume claims, exact peer/executable/config/hash binding,
watcher readiness and malformed readiness, claim expiry, duplicate local/remote launch, replay,
interrupted transport, result-transport loss, start refusal, absolute deadlines, and cleanup.
Prove:

- the watcher is transient, collected, `Restart=no`, and has no persistent timer;
- the fixed launch helper can invoke only the manifest-pinned one-shot orchestration unit;
- the success marker is withheld until executor readiness, expected peers, fresh observation,
  attestation, ledger readiness, claim consumption, live gate OFF, timer absence, and marker cleanup
  are all proven by the fixture;
- cleanup never starts a service as fallback and removes only the matching transient invocation;
- logs contain only allowlisted non-secret audit fields and terminal markers.

All systemd, journal, process, cgroup, and remote filesystem evidence must come from fixtures. The
test suite must make real `/usr/bin/ssh`, `systemctl`, and broker access unreachable.

### Packaging, install, update, rollback, and uninstall tests

Create `execution/tests/ops/test_portable_release.sh`. For each of two independent temporary HOME
and prefix directories:

1. build the exact release twice from the same source epoch;
2. compare archive and manifest hashes, file order, normalized timestamps, modes, and content;
3. install without touching the real home;
4. provision a non-secret deployment and operator/device fixture under temporary XDG config;
5. run offline doctor and every dry-run;
6. update to a second fixture version and validate the recoverable previous version;
7. roll back atomically and verify hashes;
8. uninstall using the matching installed manifest;
9. prove pre-existing and subsequently modified files remain untouched.

Add negative cases for archive traversal, symlink/hard-link substitution, changed ownership/mode,
duplicate manifest paths, partial install, concurrent install/update, interrupted atomic switch,
wrong prior-version digest, manifest tampering, foreign current symlink, and uninstall with a
mismatched manifest. Installed hashes in the two environments must be identical. Describe this as
two isolated-home portability evidence, not cross-architecture proof.

## Files and layout

Create this canonical source layout:

- `execution/ops/kotak` — portable command dispatcher;
- `execution/ops/libexec/kotak-auth-helper` — local-to-remote fixed authentication transport helper;
- `execution/ops/libexec/kotak-remote-doctor` — fixed read-only remote compatibility protocol;
- `execution/ops/libexec/shaurya-shadow-watcher` — generalized finite one-shot watcher source;
- `execution/ops/libexec/shaurya-session-broker` — bounded single-use non-secret launch/session
  handoff source;
- `execution/ops/manifests/deployment.example.json` — exact-schema non-secret example;
- `execution/ops/manifests/operator-device.example.json` — non-secret identity example;
- `execution/ops/package_release.sh` — reproducible release builder;
- `execution/ops/verify_manifest.sh` — offline release/installed-manifest verifier;
- `execution/ops/install.sh` — prefix-scoped user installer/update entrypoint;
- `execution/ops/uninstall.sh` — matching-manifest removal entrypoint;
- `execution/ops/README.md` — command and release format summary.

Use a versioned installed layout beneath a user-selected prefix, with a default of
`$HOME/.local`: `libexec/kotak/releases/<version>/` contains immutable release files and
`bin/kotak` selects the validated current release through an atomic pointer. Configuration lives in
`${XDG_CONFIG_HOME:-$HOME/.config}/kotak`; state, locks, and mode-0600 logs live in
`${XDG_STATE_HOME:-$HOME/.local/state}/kotak`. Reject empty, relative, root, home-root, or
symlink-escaped prefixes. Never infer an SSH private-key path or install identity material.

Release packaging may use repository tooling, but the installed CLI must restrict itself to
commands available on supported Macs or report a precise doctor failure. Do not assume GNU `stat`,
`date`, `sha256sum`, `/usr/bin/python3`, or a package manager locally. GNU-specific commands remain
inside the fixed Linux remote helpers. Disable locale/time variation, sort every manifest path,
normalize release timestamps to `SOURCE_DATE_EPOCH`, and pin modes before hashing.

## Exact manifests

Use strict canonical UTF-8 JSON parsed without shell evaluation.

The release manifest records schema version, release version, compatibility version, source commit,
source epoch, archive digest, and for every installed relative path its SHA-256 digest, size, mode,
and role. Relative paths must be normalized, unique, and contained beneath the release directory.
Checksums are called checksums unless an actual signing key and trust policy are introduced.

The deployment manifest contains only bounded data fields: schema/deployment/compatibility versions,
SSH host alias, expected remote OS/architecture, executor commit, clean source-tree digest, build
digest, deployment-manifest digest, remote installation root, fixed helper/watcher paths and
digests, fixed orchestration unit,
expected protocol versions, and bounded timeouts. It contains no arbitrary commands, options,
environment assignments, credential paths, or shell fragments. The CLI constructs fixed remote
commands and treats every field as data.

The operator/device manifest contains configured operator ID, device ID, non-secret SSH public-key
fingerprint, and schema version. IDs use a bounded printable syntax and are not inferred from a
username or hostname. The CLI combines it with release/deployment digests, executor commit/build,
requested mode, confirmation type, timestamp, and invocation ID to create the exact launch
attestation consumed by the executor. Never include private-key material or TOTP.

## Command semantics

- `help` and `version` are immutable offline output.
- `doctor` is offline and read-only. `doctor --remote` adds exactly one bounded read-only SSH check.
- `auth --confirm KOTAK_AUTH` performs one explicit hidden-code diagnostic against the fixed remote
  authentication helper. It never persists a session or launches anything.
- `status` performs one bounded read-only remote status operation and emits only the fixed status
  schema.
- `prepare --confirm SHAURYA_PREPARE` validates the installed release and non-secret manifests and
  writes only a local, checksum-bound launch request in the state directory. It does not fetch
  instrument metadata, authenticate, deploy, or mutate the remote host.
- `preflight` verifies the local launch request and performs one bounded read-only remote
  compatibility/attestation check. It never starts a service.
- `shaurya-shadow-launch --confirm SHAURYA_SHADOW_LAUNCH` arms the fixed transient watcher, submits
  the non-secret launch attestation, requests the manifest-pinned one-shot orchestration unit, and
  waits for one factual terminal result. It does not authenticate to Kotak or enable a timer/live
  router.
- `shadow-launch` is a syntax-compatible alias for `shaurya-shadow-launch` with the same confirmation
  token, plans, exit codes, and markers in the Shaurya package. D51’s separate legacy wrapper keeps
  its authenticated feed behavior only behind its explicit legacy route.

Every relevant command accepts `--dry-run`, which performs parsing and safe plan rendering but no
prompt, lock, log, state mutation, hash-changing operation, or network action. Confirmations are
checked before locks, logs, prompts, or SSH. Actual-run logs are created only after validation, with
mode `0600`, and receive only marker/audit output through an allowlist rather than an unrestricted
`tee` of helper output.

## Safe installation lifecycle

The installer verifies archive and manifest before creating a version directory. It refuses to
overwrite an existing version whose bytes differ. Write into a new same-filesystem staging
directory, fsync material where supported, validate every installed byte/mode, then atomically
switch the current pointer while retaining the previous validated target for rollback. Store an
installed manifest outside the immutable release directory but under the selected prefix.

Rollback validates the requested previous release and atomically switches only the current pointer.
Uninstall removes only entries listed in the matching installed manifest whose current digest/type
still matches; it reports and preserves modified, foreign, or pre-existing paths. Remove empty
installer-owned directories from deepest to shallowest, never recursively delete a broad prefix,
home, XDG root, or unresolved variable target.

Locks use an atomic directory or equivalent primitive under XDG state, record non-secret process
identity, detect live owners, and clear only a demonstrably stale matching lock. Concurrent
operations refuse rather than race. Interrupted installs leave the old current release usable and
a separately identifiable staging directory for safe inspection/removal.

## Completion evidence

This section is complete when every hermetic command/doctor/auth/watcher/session-broker test passes,
two isolated temporary installations have byte-identical release and installed hashes, update and
rollback restore exact versions, uninstall preserves foreign files, and scans find no credentials,
private keys, TOTP, personal paths, D51 service names, unrestricted response logging, or real-home
targets. Record that no real SSH, broker authentication, AWS action, or home installation occurred,
and retain cross-architecture Mac testing as an explicit limitation unless separately performed.
