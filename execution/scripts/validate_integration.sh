#!/bin/sh
set -eu

execution_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
repository_root=$(CDPATH= cd -- "$execution_root/.." && pwd -P)
build_dir=/private/tmp/shaurya-execution-build
summary_path=
d51_root=

while [ "$#" -gt 0 ]; do
  case "$1" in
    --build-dir) [ "$#" -ge 2 ] || exit 2; build_dir=$2; shift 2 ;;
    --summary) [ "$#" -ge 2 ] || exit 2; summary_path=$2; shift 2 ;;
    --d51-root) [ "$#" -ge 2 ] || exit 2; d51_root=$2; shift 2 ;;
    *) printf '%s\n' "unknown argument: $1" >&2; exit 2 ;;
  esac
done

case "$build_dir" in /private/tmp/*) ;; *) printf '%s\n' 'build directory must be under /private/tmp' >&2; exit 2 ;; esac
if [ -n "$summary_path" ]; then
  case "$summary_path" in /private/tmp/*) ;; *) printf '%s\n' 'summary must be under /private/tmp' >&2; exit 2 ;; esac
fi
if [ -d "$build_dir" ] && [ -n "$(find "$build_dir" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
  printf '%s\n' "build directory is not empty: $build_dir" >&2
  exit 2
fi
mkdir -p "$build_dir"

cmake_bin=${CMAKE_BIN:-cmake}
ctest_bin=${CTEST_BIN:-ctest}
python_bin=${PYTHON_BIN:-python3}
routing_python=${SHAURYA_ROUTING_TEST_PYTHON:-$python_bin}
jobs=${SHAURYA_BUILD_JOBS:-4}

stage() { printf '[INTEGRATION] stage=%s status=start\n' "$1"; }
passed=0
finish() {
  status=$?
  if [ -n "$summary_path" ]; then
    if [ "$status" -eq 0 ]; then result=pass; else result=fail; fi
    printf '{"build_directory":"%s","passed_stages":%s,"result":"%s","schema_version":"1.0.0"}\n' \
      "$build_dir" "$passed" "$result" > "$summary_path"
  fi
  exit "$status"
}
trap finish EXIT HUP INT TERM

stage configure
"$cmake_bin" -S "$execution_root" -B "$build_dir" \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_TESTING=ON \
  -DSHAURYA_ENABLE_LIVE_ROUTER=OFF \
  -DSHAURYA_ENABLE_KOTAK_LIVE=OFF \
  -DSHAURYA_WARNINGS_AS_ERRORS=ON \
  -DSHAURYA_ROUTING_TEST_PYTHON="$routing_python"
passed=$((passed + 1))

stage build
"$cmake_bin" --build "$build_dir" --parallel "$jobs"
passed=$((passed + 1))

stage ctest
PYTHONDONTWRITEBYTECODE=1 "$ctest_bin" --test-dir "$build_dir" --output-on-failure
passed=$((passed + 1))

stage syntax
for script in "$execution_root"/ops/*.sh "$execution_root"/tests/ops/*.sh "$execution_root"/scripts/*.sh; do
  /bin/sh -n "$script"
done
PYTHONDONTWRITEBYTECODE=1 "$python_bin" -B - \
  "$execution_root"/ops/*.py "$execution_root"/ops/libexec/*.py \
  "$execution_root"/tests/policy/*.py "$execution_root"/tests/ops/*.py <<'PY'
import sys
for name in sys.argv[1:]:
    with open(name, "rb") as source:
        compile(source.read(), name, "exec")
PY
passed=$((passed + 1))

if [ -n "$d51_root" ]; then
  stage audit
  "$execution_root/scripts/audit_release.sh" --d51-root "$d51_root"
  passed=$((passed + 1))
fi

printf '[INTEGRATION] status=pass stages=%s repository=%s\n' "$passed" "$repository_root"
trap - EXIT HUP INT TERM
finish
