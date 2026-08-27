#!/bin/sh
set -eu

execution_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
repository_root=$(CDPATH= cd -- "$execution_root/.." && pwd -P)
d51_root=
start_commit=bcb6dea02329f824c82488f29450af0dd0e826ca

while [ "$#" -gt 0 ]; do
  case "$1" in
    --d51-root) [ "$#" -ge 2 ] || exit 2; d51_root=$2; shift 2 ;;
    --start-commit) [ "$#" -ge 2 ] || exit 2; start_commit=$2; shift 2 ;;
    *) printf '%s\n' "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ -n "$d51_root" ] && git -C "$d51_root" rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
  printf '%s\n' '--d51-root must name the D51 Git worktree' >&2
  exit 2
}

fail() { printf '[AUDIT] status=fail reason=%s\n' "$1" >&2; exit 1; }
check_names() {
  root=$1
  scope=$2
  git -C "$root" ls-files -- "$scope" | while IFS= read -r tracked; do
    case "/$tracked/" in
      */__pycache__/*|*/.venv/*|*/.pytest_cache/*|*/CMakeFiles/*|*/build/*|*/cache/*)
        fail "tracked runtime path: $tracked" ;;
    esac
    case "$tracked" in
      *.pyc|*.pyo|*.pem|*.key|*.token|*.sock|*.log) fail "tracked runtime or secret file: $tracked" ;;
      .env|*/.env) fail "tracked secret environment file: $tracked" ;;
      */state/*|*/stats/*|*/logs/*) [ "${tracked##*/}" = .gitkeep ] || fail "tracked runtime output: $tracked" ;;
    esac
  done
}
scan_content() {
  root=$1
  scope=$2
  if git -C "$root" grep -I -n -E \
    'BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY|AKIA[0-9A-Z]{16}|aws_secret_access_key[[:space:]]*[:=][[:space:]]*[^$<{[:space:]]' \
    -- "$scope" ':!execution/docs/planning' >/private/tmp/shaurya-audit-secret.txt; then
    cat /private/tmp/shaurya-audit-secret.txt >&2
    fail 'secret-like tracked content'
  fi
  personal_root='/''Users/'
  if git -C "$root" grep -I -n "$personal_root" -- "$scope" ':!execution/docs/planning' \
      >/private/tmp/shaurya-audit-paths.txt; then
    cat /private/tmp/shaurya-audit-paths.txt >&2
    fail 'personal absolute path'
  fi
}

printf '[AUDIT] stage=diff-check\n'
git -C "$repository_root" diff --check
git -C "$d51_root" diff --check

printf '[AUDIT] stage=protected-projects\n'
[ -z "$(git -C "$repository_root" diff --name-only "$start_commit"...HEAD -- data research)" ] ||
  fail 'committed Data or Research change'
[ -z "$(git -C "$repository_root" status --porcelain -- data research)" ] ||
  fail 'staged or untracked Data or Research change'

printf '[AUDIT] stage=tracked-paths\n'
check_names "$repository_root" execution
check_names "$d51_root" .

printf '[AUDIT] stage=secrets-and-paths\n'
scan_content "$repository_root" execution
scan_content "$d51_root" .

printf '[AUDIT] stage=dependency-direction\n'
PYTHONDONTWRITEBYTECODE=1 "${PYTHON_BIN:-python3}" \
  "$execution_root/tests/policy/test_dependency_boundaries.py" \
  --repo-root "$repository_root" --start-commit "$start_commit"

printf '[AUDIT] stage=live-gates\n'
grep -q 'SHAURYA_ENABLE_KOTAK_LIVE must remain OFF' "$execution_root/CMakeLists.txt" ||
  fail 'Shaurya live gate missing'
grep -q 'ALO_ENABLE_LIVE_ROUTER' "$d51_root/CMakeLists.txt" || fail 'D51 live gate missing'
grep -q 'message(FATAL_ERROR' "$d51_root/CMakeLists.txt" || fail 'D51 fatal live refusal missing'

printf '[AUDIT] status=pass protected_diff=empty repositories=2\n'
