# Restore on a New Mac

1. Obtain the release archive and external manifest through an authenticated artifact channel.
2. Verify both with `ops/verify_manifest.sh`; do not install an unverified or locally edited bundle.
3. Install to a new user prefix as described in `INSTALL.md`, then run offline `help`, `version`, and
   `doctor` before adding any machine-specific configuration.
4. Create a new Ed25519 operator identity on the new Mac. Provision only its public key and fixed
   forced-command restriction on the execution host. Do not copy a private key, TOTP seed, broker
   session, credential file, runtime ledger, socket, or state directory from the old device.
5. Pin the host key in the new device's protected `known_hosts`; update the operator-device manifest
   with the new public-key fingerprint and device identity.
6. Have the second authorized device independently verify the deployment manifest, executor build,
   protocol versions, helper hashes, and disabled live gate.
7. Run one bounded `kotak doctor --remote`, then `kotak prepare --confirm SHAURYA_PREPARE`. Stop if
   either result is unavailable or unverified.
8. Start only a new shadow session with a new invocation/session identity. Never reuse an in-flight
   session or translate an old backend's open orders.

The current test evidence covers fixture-backed restoration mechanics, not a physical second Mac,
real SSH host, broker authentication, or live order path.
