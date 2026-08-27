# Install and Package Verification

All examples below are offline and use a caller-owned prefix. A release consists of a `.tar.gz`
archive plus its external canonical manifest. Verify before installing:

```sh
execution/ops/verify_manifest.sh kotak-1.0.0.manifest.json kotak-1.0.0.tar.gz
execution/ops/install.sh --prefix "$HOME/.local" \
  --archive kotak-1.0.0.tar.gz --manifest kotak-1.0.0.manifest.json
"$HOME/.local/bin/kotak" help
"$HOME/.local/bin/kotak" version
"$HOME/.local/bin/kotak" doctor
```

`doctor` without `--remote` is local and offline. Remote doctor is a separate, bounded, read-only
operation and is not part of installation. Operator identity and known-hosts files are provisioned
by the operator; the package never creates or copies credentials.

Install a verified newer release with the same `install.sh` command. Roll back only while no
session is active:

```sh
execution/ops/install.sh --prefix "$HOME/.local" --rollback 1.0.0
```

Uninstall is manifest-scoped and digest-conditional:

```sh
execution/ops/uninstall.sh --prefix "$HOME/.local" \
  --installed-manifest "$HOME/.local/libexec/kotak/installed-manifest.json"
```

It removes only installer-owned, identity-checked paths and preserves foreign or modified files.
The hermetic portable release suite performs two independent installs, compares archive and
installed-manifest hashes, exercises update/rollback/interruption recovery, and verifies scoped
uninstall. It never targets the real home or system prefix.
