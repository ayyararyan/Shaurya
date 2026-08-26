# Secret handling and migration policy

This document is the security-policy artifact for `REQ-INF-05`. `TASKS.md` remains the
sole status ledger.

## Binding policy

- Shaurya configuration carries a credential **handle**, never a credential value. A handle
  may name an environment variable or reference a credential file outside a Git tree.
- Credential values live outside Shaurya and strategy source trees.
- Each external credential directory has mode `700`; each credential file has mode `600`.
- Credential values are deliberately unobserved by Shaurya: they must not be committed,
  copied into artifacts, or written to logs.

`src/shaurya/contracts/config.py::CredentialHandle` is the shared configuration object.
`ShauryaConfig` rejects undeclared fields, including an attempted raw `access_token`; the
regression coverage is `test_config_rejects_secret_values_and_unknown_fields`.

This is the pattern already used by Market Making at
`~/Documents/Market-Making-Secrets`: the directory is mode `700`, its credential files are
mode `600`, and source code receives an external path rather than embedding a value.

## 2026-08-18 value-redacted migration inventory

The Google Drive entries below were staged with `gdrive-safe`; only paths, file metadata,
and source-code readers were inspected. No credential value was read or printed.

### `Dhandho/.env`

- The file exists in Drive.
- No explicit reader of this exact path was found after searching the staged source for all
  six strategy directories. Mushin Gamma explicitly checks its own `.env`, Still Water's
  production `.env`, and `Dhandho/strategy/.env` (not `Dhandho/.env`). Shoshin and two Still
  Water utilities call `load_dotenv()` without a path, but each currently has a nearer
  strategy-local `.env`; this is not evidence that they read the Dhandho-root file.
- Relocation is blocked because neither an exact external destination nor a confirmed reader
  to update is specified. The original remains untouched.

### `Dhandho/strategy/VOLARB/voltaire/config/`

- `src/auth/kite_auth.py::KiteAuth` defaults to `config/credentials_local.yaml`, derives
  `.access_token` and `.encryption_key` as siblings, reads the YAML credentials and both
  token/key files, and writes refreshed token/key files there. The default constructor is
  used by the option-chain fetcher, historical fetcher, Kite client, and Greeks CLI path.
- No source reader of `credentials.yaml` was found; it is nevertheless one of the four
  credential-shaped files explicitly listed for relocation.
- All four originals (`.access_token`, `.encryption_key`, `credentials.yaml`, and
  `credentials_local.yaml`) remain untouched because their exact external destination is
  not specified.

### `Dhandho/strategy/Still_Water/production_engine/.env` and `keys/`

- `scripts/dhan_bootstrap.py` reads `ENV_FILE`, defaulting to `.env`.
- `scripts/daily_bootstrap.py` reads and updates its `--env-file` (default `.env`) and writes
  `KITE_ACCESS_TOKEN.txt` under its `--keys-dir` (default `keys`).
- `src/engine/dhan_connector.py` and `scripts/smoke_test_dhan.py` use default dotenv lookup;
  the production run/deploy scripts execute from the production-engine root. The S3 helper
  explicitly sources the root `.env`; EC2 deployment helpers also reference that path.
- The staged `keys/` directory contains one listed credential-shaped file,
  `KITE_ACCESS_TOKEN.txt`.
- Both originals remain untouched because their exact external destination is not specified.

### `Dhandho/strategy/Seshin_Zen/production_engine/.env`

- `src/engine/main.py` explicitly loads the production-engine root `.env`.
- `scripts/daily_bootstrap.py` reads and updates the same file. Its fallback key directory is
  a separate hard-coded Drive path (`Dhandho/Still_Water/keys`), not the Still Water
  `production_engine/keys/` directory listed above.
- The original remains untouched because its exact external destination is not specified.

### `My Drive/Market Making/dhan_credentials.env`

- `gdrive-safe status` and a refreshed fetch both report that this old Drive path no longer
  exists.
- The pre-existing personal-Mac `~/Documents/Secrets/` to office-Mac
  `~/Documents/Market-Making-Secrets/` one-way mirror already represents this credential as
  `dhan.env`. On the office Mac, the mirror is mode `700`, `dhan.env` is mode `600`, and
  `scripts/dat09_concurrency_probe.py` reads that external file.
- This item is already handled by the pre-existing Market-Making-Secrets system. It was not
  moved, copied, or recreated by INF-06.

## INF-06 stop condition

The exact destination naming/location for the other eight existing files is not fixed by
`TASKS.md`, `docs/module-spec/INF.md`, or the harvested Market Making pattern. Choosing names
would create policy rather than implement it. No original may be deleted and no strategy
reader may be redirected until those exact destinations are approved; consequently no Drive
copy/checksum verification is applicable to this run.
