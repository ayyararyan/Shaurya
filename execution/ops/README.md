# Portable Kotak operator lane

`kotak` is the Shaurya-owned, once-per-session operator control plane. It is not an order router.
The packaged entrypoints expose no environment, flag, or file-based fixture override. A POSIX
bootstrap keeps `help`, `version`, and a factual `doctor` failure available without Python. Other
commands use only the fixed platform `/usr/bin/python3` bootstrap and accept it only after an
isolated Python 3.9-or-newer version, executable, ownership, mode, and resolved-ancestor check. `PATH` and
`KOTAK_PYTHON` are ignored. Missing trusted dependencies fail closed before remote or installation
work. No bundled interpreter is claimed by this release.

Offline commands are `help`, `version`, and `doctor`. Explicit remote commands use one non-PTY,
batch-only SSH process with password, keyboard-interactive authentication, agent forwarding, and
all forwarding disabled. They use only the fixed user-provisioned
`${XDG_CONFIG_HOME:-$HOME/.config}/kotak/operator_ed25519` identity after no-follow owner, mode-0600,
and ancestor validation. Bounded validated bytes are copied into mode-0600 regular snapshots under
`/private/tmp`, reopened read-only, and unlinked before process creation. The source and snapshot
descriptors are rehashed immediately before SSH, so in-place or pathname mutation is refused and no
named snapshot remains. The
derived public-key fingerprint must equal the operator manifest. The same protected config directory
must contain a mode-0600 `known_hosts` file with the exact host alias; SSH receives its descriptor
with global host-key files and host-key updates disabled. The package never creates or installs either
trust file. `auth --confirm KOTAK_AUTH`
is a synthetic transport diagnostic only and can never claim authentication. It reads a six-digit code
from the controlling terminal with echo disabled only after a separate secret-free doctor request
matches the pinned deployment and helper measurements. The server-side operator key must be
provisioned with the exact root-owned `kotak-remote-doctor` forced command; the client sends only
`shaurya-operator-v1 <operation>`, and no deployment-selected pathname receives input.
`prepare --confirm SHAURYA_PREPARE` writes a mode-0600 launch request. `preflight`,
`status`, and `shaurya-shadow-launch --confirm SHAURYA_SHADOW_LAUNCH` consume strict closed
protocols. The production launch helper writes one bounded claim, invokes the sibling single-use
broker, starts only the invocation-bound `shaurya-shadow-once@UUID.service` instance from the pinned
`shaurya-shadow-once@.service` template, and waits through the sibling finite watcher. Non-packaged
tests import pure orchestration functions and inject explicit fake dependency objects. `shadow-launch`
is an exact alias and never selects a legacy authenticated route.

Remote compatibility binds the opened executor image to its compiled 40-hex commit,
`source_state=clean`, deployment-pinned source-tree SHA-256, and opened-image SHA-256. Dirty,
missing, or mismatched source evidence is refused for doctor, auth preflight, status, preflight, and
launch.

Every relevant command supports `--dry-run`; required confirmations remain mandatory in dry-run mode.
Dry runs and confirmation refusals happen before state,
locks, prompts, or SSH. Terminal output is limited to the closed marker grammar:

```text
[KOTAK_RESULT] command=NAME status=STATUS code=N verified=yes|no
```

## Release lifecycle

`package_release.sh` requires the exact CLI version and a 40-hex source revision equal to the locally
measured Git `HEAD`, embeds it as manifest-owned `SOURCE_REVISION`, then creates deterministic
gzip/tar bytes and a canonical external checksum manifest. `verify_manifest.sh` validates strict schema, sorted contained paths, sizes, modes, and
SHA-256 checksums. `install.sh` uses the isolated `$HOME/.local` default or an explicit absolute prefix, extracts regular files to a
same-filesystem staging directory, verifies every byte and mode, and atomically switches `current`.
The prior target remains under `previous`; `install.sh --rollback VERSION` validates before switching.
`uninstall.sh` requires the matching installed manifest and removes only unchanged installer-owned
entries. During an interrupted update, an invocation-independent fallback pointer keeps the old
launcher runnable until descriptor-safe recovery completes. Uninstall remains fail closed and resumes
across content, manifest, and directory removal boundaries. Foreign and modified paths are preserved.

State, audit, and installation directories are traversed descriptor-relative without following symlinks.
The prefix lock is a kernel advisory lock on an owner-only regular inode; process exit releases it,
so a dead owner is recoverable without deleting a possibly replaced path. Prefix identity is
revalidated before release and pointer mutations.

Configuration is under `${XDG_CONFIG_HOME:-$HOME/.config}/kotak`, state under
`${XDG_STATE_HOME:-$HOME/.local/state}/kotak`, the prefix-scoped atomic release lock under the selected
prefix, and immutable releases under its `libexec/kotak/releases/`. Identity manifests contain only bounded operator/device IDs and
a public-key fingerprint. They never contain private-key paths, credentials, TOTP values, broker
responses, or arbitrary remote shell fragments.

The tests under `execution/tests/ops/` use isolated `/private/tmp` homes and a recording SSH fixture.
They do not contact a host, authenticate to a broker, invoke a service manager, or install into the
real home. Passing two isolated-home tests is portability evidence only, not cross-architecture Mac
certification.
