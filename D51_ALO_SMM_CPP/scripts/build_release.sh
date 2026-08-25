#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
rm -rf "$ROOT/build"
cmake -S "$ROOT" -B "$ROOT/build" -G Ninja -DCMAKE_BUILD_TYPE=Release -DALO_ENABLE_LIVE_ROUTER=OFF -DALO_BUILD_TESTS=ON -DALO_NATIVE_TUNE=ON
cmake --build "$ROOT/build" -j "$(nproc)"
ctest --test-dir "$ROOT/build" --output-on-failure
"$ROOT/build/alo-smm" --config "$ROOT/config/alo_smm.json" --self-test
printf '\nBuilt SHADOW-ONLY binary: %s/build/alo-smm\n' "$ROOT"
