# Portable operator CLI and release safety

The canonical operator entrypoint is `execution/ops/kotak`. Its remote surface is deliberately
small: one SSH process sends a closed operation token to a server-side forced command, and all helper output must match
a closed JSON response schema before a success marker is emitted. Remote strings are passed as
individual arguments without shell evaluation. Authentication and Shaurya shadow launch are
separate commands; shadow launch never requests a TOTP or uses the authentication helper.

Exit classes are stable: `0` success, `2` usage or pre-work refusal, `3` verified remote refusal,
`4` bounded timeout, `5` unavailable terminal result, and `70` integrity failure. Markers contain no
paths, instruments, payloads, remote response bodies, usernames, or secrets.

Release archives contain only regular files named by the external canonical release manifest.
Packaging requires the package version to equal the CLI's exact version and requires its
40-lowercase-hex source commit to equal locally measured Git `HEAD`; generated `SOURCE_REVISION`
bytes are covered by the archive and installed manifests. The source commit records repository
provenance while the archive digest records the exact packaged bytes. Packaging normalizes order,
timestamps, owners, groups, and modes.
Install and uninstall default to `$HOME/.local` (tests replace `HOME` with isolated temporary homes).
Installation rejects traversal,
links, unsafe prefixes, foreign launchers/current pointers, concurrent operations, and hash or mode
drift. Atomic pointer replacement leaves the prior release recoverable. Removal is manifest-scoped
and digest-conditional through a durable uninstall transaction; it is never a recursive deletion of
a prefix, home, or XDG root. The prefix-scoped lock, journals, pointers, indexes, release trees, and
owned-file removal remain bound to held directory descriptors across mutation.

The remote helper implements a closed production protocol. Read-only operations remeasure the
deployment, protocol implementation, sibling helpers, and exact root-owned unit template. The
executor's exact version line supplies its compiled 40-hex source commit, clean/dirty source state,
source-tree SHA-256, and the digest of its currently opened executable. The doctor independently
hashes that same protected executable and requires the commit, `source_state=clean`, source-tree
digest, and opened-image digest to match the protected deployment. Status-file assertions alone
never establish those facts. The operator key must be provisioned server-side with the fixed root-owned
`kotak-remote-doctor` forced command and shell, PTY, forwarding, and arbitrary-command access
disabled. The client requests only `shaurya-operator-v1 <operation>`; the wrapper rejects every
other `SSH_ORIGINAL_COMMAND`. Authentication performs a separate secret-free doctor connection,
verifies the complete deployment and helper digests, and only then prompts for diagnostic bytes and
executes the digest-checked authentication helper from its held descriptor.
Launch re-attests the currently installed local release, validates the checksum-bound request,
creates one mode-0600 attestation and claim under the fixed protected root, invokes the digest-checked
sibling broker, and returns success only after the sibling
watcher validates `Restart=no`, timer absence, live gate OFF, fresh observation, expected peers,
attestation, ledger readiness, consumed claim, and identity-checked evidence cleanup. The broker can
start only `shaurya-shadow-once@UUID.service`, where UUID is the canonical invocation ID, through
fixed `/usr/bin/systemctl` arguments. The pinned `shaurya-shadow-once@.service` content supplies the
exact executor config and `--launch-attestation /run/shaurya-execution/claims/%i.json` binding with
`Restart=no` and no timer. There is no command, unit, path, or environment expansion from a manifest.
Successful invocations retain a directory-fsynced immutable remote tombstone keyed by invocation ID,
request digest, session, unit, config, and terminal response. A crash in the `completing` phase
resumes bounded stop and identity-checked artifact cleanup, then atomically promotes the tombstone to
`completed`. A retry after transport loss returns only that exactly correlated result and cannot
restart broker, watcher, or unit. The local request is then replaced by an
immutable consumed record, so loss of either side alone cannot enable replay.

Production entrypoints always construct fixed dependencies and accept no test-mode downgrade.
Hermetic tests directly import the pure operations and pass dependency objects from non-packaged
fixture drivers. Release scans reject fixture override names in installed bytes. Tests execute the
complete doctor-to-broker-to-watcher chain with all real SSH, systemd, broker, and network access
unreachable.

Local shell entrypoints do not depend on `PATH` or an interpreter environment variable. Help and
version are shell-only, while doctor emits the closed `python_unavailable` integrity marker if no
runtime is available. Python-backed commands probe a closed absolute candidate list and require an
isolated self-attestation of the interpreter version, executable location, owner, mode, and resolved
ancestors. This is a portable bootstrap strategy, not a claim that the current archive bundles a
Python runtime or proves cross-architecture compatibility.

SSH uses only `/usr/bin/ssh`, the fixed user-provisioned
`${XDG_CONFIG_HOME:-$HOME/.config}/kotak/operator_ed25519` identity, and the equally fixed
`known_hosts` sibling. Neither path is selected by a manifest or override, and neither file is
installed or created by this package. Their private ancestors, regular-file types, owners, and exact
mode 0600 are checked; both are opened without following links, copied into bounded mode-0600 regular
snapshots beneath `/private/tmp`, reopened read-only, and unlinked before process creation. The
source descriptors and snapshots are rehashed for byte identity immediately before the one
deadline-bounded SSH attempt. A mutation refuses without an SSH process and no named snapshot
remains. The public identity derived from the snapshot private key must equal the protected operator
fingerprint, and the host alias must be pinned in the snapshot known-hosts file.

Config, state, audit, lock, and installation roots are opened component-by-component without
following symlinks. Private leaf directories must be owner-only. A prefix-scoped regular lock file is
held with a kernel advisory lock; stale process text alone cannot block recovery, and a live lock
cannot be stolen. Update writes its recovery journal before publishing changes and leaves an old
launcher target executable across every injected interruption. Uninstall records a durable journal
and removes only identity-checked manifest-owned leaves, directories, and metadata in a recoverable
order; it never recursively removes a path that could have been replaced.

All current validation evidence is hermetic. Real SSH, Kotak authentication, AWS/service mutation,
real-home installation, and cross-architecture Mac execution remain outside this implementation.
