#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
[[ -x build/alo-smm ]] || { echo "build/alo-smm missing; run scripts/build_release.sh" >&2; exit 2; }
./scripts/preflight_shadow.sh

# Snapshot only non-secret run metadata. Credentials remain in the external EnvironmentFile.
DAY="$(date -u +%F)"
RUN_DIR="stats/$DAY"
mkdir -p "$RUN_DIR"
cp config/alo_smm.json "$RUN_DIR/run_config.json"
cp config/instruments.csv "$RUN_DIR/instruments.csv"
cp VERSION "$RUN_DIR/VERSION"
sha256sum build/alo-smm config/alo_smm.json config/instruments.csv > "$RUN_DIR/run_hashes.sha256"
{
  echo "started_utc=$(date -u +%FT%TZ)"
  echo "hostname=$(hostname)"
  echo "kernel=$(uname -sr)"
  echo "machine=$(uname -m)"
} > "$RUN_DIR/run_environment.txt"

exec ./build/alo-smm --config config/alo_smm.json
