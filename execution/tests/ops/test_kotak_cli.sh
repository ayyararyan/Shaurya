#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
tmp=$(mktemp -d /private/tmp/shaurya-ops-cli.XXXXXX)
if [ "${FIXTURE_DEBUG:-0}" = 1 ]; then
  printf 'FIXTURE_TMP=%s\n' "$tmp" >&2
else
  trap 'find "$tmp" -depth -delete' EXIT INT TERM
fi
kotak="$root/tests/ops/fixtures/portable_fixture_driver.py"
export PYTHONDONTWRITEBYTECODE=1 HOME="$tmp/home" XDG_CONFIG_HOME="$tmp/config" XDG_STATE_HOME="$tmp/state"
export FIXTURE_SSH_BIN="$root/tests/ops/fixtures/bin/ssh" FIXTURE_SSH_RECORD="$tmp/ssh.record"
export FIXTURE_RESPONSE_DIR="$tmp/responses" FIXTURE_REPO_ROOT="$root"
export FIXTURE_SSH_IDENTITY="$XDG_CONFIG_HOME/kotak/operator_ed25519"
export FIXTURE_TRANSPORT_SNAPSHOT_ROOT="$tmp/held"
mkdir -p "$HOME" "$XDG_CONFIG_HOME/kotak" "$tmp/responses" "$tmp/chain" "$tmp/held"
chmod 700 "$HOME" "$XDG_CONFIG_HOME" "$XDG_CONFIG_HOME/kotak" "$tmp/chain" "$tmp/held"
/usr/bin/ssh-keygen -q -t ed25519 -N '' -f "$FIXTURE_SSH_IDENTITY"
chmod 600 "$FIXTURE_SSH_IDENTITY"
cp "$root/ops/manifests/deployment.example.json" "$XDG_CONFIG_HOME/kotak/deployment.json"
cp "$root/ops/manifests/operator-device.example.json" "$XDG_CONFIG_HOME/kotak/operator-device.json"
python3 -B - "$FIXTURE_SSH_IDENTITY.pub" "$XDG_CONFIG_HOME/kotak/operator-device.json" "$XDG_CONFIG_HOME/kotak/known_hosts" <<'PY'
import base64,hashlib,json,sys
public=open(sys.argv[1]).read().strip().split(); blob=base64.b64decode(public[1])
fingerprint='SHA256:'+base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip('=')
p=sys.argv[2]; value=json.load(open(p)); value['public_key_fingerprint']=fingerprint
open(p,'w').write(json.dumps(value,sort_keys=True,separators=(',',':'))+'\n')
open(sys.argv[3],'w').write('shaurya-fixture '+public[0]+' '+public[1]+'\n')
PY
chmod 600 "$XDG_CONFIG_HOME/kotak/known_hosts"
cat > "$tmp/release.json" <<'EOF'
{"archive_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","compatibility_version":"1","files":[{"mode":"0644","path":"fixture","role":"fixture","sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","size":1}],"release_version":"1.0.0","schema_version":"1.0.0","source_commit":"1111111111111111111111111111111111111111","source_epoch":1}
EOF
chmod 644 "$tmp/release.json"; export FIXTURE_RELEASE_MANIFEST="$tmp/release.json"
python3 -B - "$XDG_CONFIG_HOME/kotak/deployment.json" "$tmp/responses/doctor.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1])); value={"status":"ok","remote_os":d["expected_remote_os"],"remote_architecture":d["expected_remote_architecture"],
"executor_commit":d["executor_commit"],"executor_source_state":"clean","executor_source_tree_sha256":d["executor_source_tree_sha256"],"executor_build_digest":d["executor_build_digest"],"deployment_digest":d["deployment_manifest_digest"],
"live_gate":"OFF","unit_status":"inactive","timer_present":False,"protocol_versions":d["protocol_versions"],
"auth_helper_digest":d["auth_helper_digest"],"doctor_helper_digest":d["doctor_helper_digest"],"broker_helper_digest":d["broker_helper_digest"],
"protocol_helper_digest":d["protocol_helper_digest"],"watcher_digest":d["watcher_digest"],"orchestration_unit":d["orchestration_unit"],"unit_template_digest":d["unit_template_digest"],"execution_session_id":"00000000-0000-4000-8000-000000000003"}
open(sys.argv[2],'w').write(json.dumps(value,sort_keys=True,separators=(',',':'))+'\n')
PY
cp "$tmp/responses/doctor.json" "$tmp/responses/status.json"
cp "$tmp/responses/doctor.json" "$tmp/responses/preflight.json"
export FIXTURE_REMOTE_STATUS="$tmp/responses/doctor.json" FIXTURE_CHAIN_ROOT="$tmp/chain" FIXTURE_CHAIN_RECORD="$tmp/chain.record"

"$kotak" help | grep -q '^kotak 1.0.0$'
"$kotak" version | grep -q 'compatibility=1'
"$kotak" doctor --dry-run | grep -q 'status=dry_run'
"$kotak" status --dry-run | grep -q 'status=dry_run'
"$kotak" preflight --dry-run | grep -q 'status=dry_run'
"$kotak" auth --dry-run --confirm KOTAK_AUTH | grep -q 'status=dry_run'
"$kotak" prepare --dry-run --confirm SHAURYA_PREPARE | grep -q 'status=dry_run'
"$kotak" shaurya-shadow-launch --dry-run --confirm SHAURYA_SHADOW_LAUNCH | grep -q 'status=dry_run'
"$kotak" shadow-launch --dry-run --confirm SHAURYA_SHADOW_LAUNCH | grep -q 'status=dry_run'
for pair in 'auth WRONG' 'prepare WRONG' 'shaurya-shadow-launch WRONG'; do
  set -- $pair
  if "$kotak" "$1" --dry-run --confirm "$2" >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
done
[ ! -e "$tmp/ssh.record" ] && [ ! -e "$XDG_STATE_HOME/kotak" ]
"$kotak" doctor --remote | grep -q 'status=success code=0 verified=yes'
[ "$(grep -c '^BEGIN$' "$tmp/ssh.record")" -eq 1 ]
# The injected lane refuses a production SSH executable before process creation.
before=$(grep -c '^BEGIN$' "$tmp/ssh.record")
if FIXTURE_SSH_BIN=/usr/bin/ssh "$kotak" doctor --remote >/dev/null 2>&1; then exit 1; fi
[ "$(grep -c '^BEGIN$' "$tmp/ssh.record")" -eq "$before" ]
for option in '-F' '/dev/null' '-oStrictHostKeyChecking=yes' '-oConnectionAttempts=1' '-oPermitLocalCommand=no' '-oProxyCommand=none' '-oProxyJump=none' '-oRequestTTY=no' '-oGlobalKnownHostsFile=/dev/null' '-oUpdateHostKeys=no'; do
  grep -Fq "arg=$option" "$tmp/ssh.record"
done
grep -Eq '^arg=-oUserKnownHostsFile=/dev/fd/[0-9]+$' "$tmp/ssh.record"
grep -A1 '^arg=-i$' "$tmp/ssh.record" | grep -Eq '^arg=/dev/fd/[0-9]+$'
grep -q '^identity_fd_consumed=yes$' "$tmp/ssh.record"
grep -q '^known_hosts_fd_consumed=yes$' "$tmp/ssh.record"
grep -q '^transport_fds_unlinked_read_only=yes$' "$tmp/ssh.record"
grep -q '^arg=shaurya-operator-v1$' "$tmp/ssh.record"
# Syntactically valid but mismatched remote evidence is unavailable, not internal.
cp "$tmp/responses/doctor.json" "$tmp/responses/doctor.saved"
python3 -B - "$tmp/responses/doctor.json" <<'PY'
import json,sys
p=sys.argv[1]; value=json.load(open(p)); value["executor_commit"]="f"*40
open(p,"w").write(json.dumps(value,sort_keys=True,separators=(",",":"))+"\n")
PY
if "$kotak" doctor --remote >/dev/null; then exit 1; else [ "$?" -eq 5 ]; fi
cp "$tmp/responses/doctor.saved" "$tmp/responses/doctor.json"
# Dirty, missing, or wrong source-tree evidence is terminally unverified.
for mutation in dirty missing wrong; do
  python3 -B - "$tmp/responses/doctor.json" "$mutation" <<'PY'
import json,sys
p,mutation=sys.argv[1:]; value=json.load(open(p))
if mutation == "dirty": value["executor_source_state"]="dirty"
elif mutation == "missing": del value["executor_source_tree_sha256"]
else: value["executor_source_tree_sha256"]="f"*64
open(p,"w").write(json.dumps(value,sort_keys=True,separators=(",",":"))+"\n")
PY
  before=$(grep -c '^BEGIN$' "$tmp/ssh.record")
  if "$kotak" doctor --remote >/dev/null; then exit 1; else [ "$?" -eq 5 ]; fi
  [ "$(grep -c '^BEGIN$' "$tmp/ssh.record")" -eq $((before + 1)) ]
  cp "$tmp/responses/doctor.saved" "$tmp/responses/doctor.json"
done
before=$(grep -c '^BEGIN$' "$tmp/ssh.record")
export FIXTURE_SSH_EXIT=255
if "$kotak" doctor --remote >/dev/null; then exit 1; else [ "$?" -eq 5 ]; fi
unset FIXTURE_SSH_EXIT
[ "$(grep -c '^BEGIN$' "$tmp/ssh.record")" -eq $((before + 1)) ]
before=$(grep -c '^BEGIN$' "$tmp/ssh.record")
export FIXTURE_SSH_EXIT=5
if "$kotak" doctor --remote >/dev/null; then exit 1; else [ "$?" -eq 5 ]; fi
unset FIXTURE_SSH_EXIT
[ "$(grep -c '^BEGIN$' "$tmp/ssh.record")" -eq $((before + 1)) ]

if "$kotak" prepare >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
FIXTURE_INVOCATION_ID=00000000-0000-4000-8000-000000000004 "$kotak" prepare --confirm SHAURYA_PREPARE | grep -q 'status=success'
[ "$(stat -f '%Lp' "$XDG_STATE_HOME/kotak/launch-request.json")" = 600 ]
python3 -B - "$XDG_STATE_HOME/kotak/launch-request.json" <<'PY'
import json,sys
v=json.load(open(sys.argv[1])); assert v['public_key_fingerprint'].startswith('SHA256:') and v['confirmation_type']=='SHAURYA_PREPARE'
PY
"$kotak" preflight | grep -q 'status=success'
"$kotak" status | grep -q 'status=success'

# Launch remeasures the same clean source identity before any broker/watcher work.
cp "$tmp/responses/doctor.json" "$tmp/launch-status.saved"
python3 -B - "$tmp/responses/doctor.json" <<'PY'
import json,sys
p=sys.argv[1]; value=json.load(open(p)); value["executor_source_state"]="dirty"
open(p,"w").write(json.dumps(value,sort_keys=True,separators=(",",":"))+"\n")
PY
: > "$tmp/chain.record"
broker_before=$(grep -c '^broker$' "$tmp/chain.record" 2>/dev/null || true)
if "$kotak" shaurya-shadow-launch --confirm SHAURYA_SHADOW_LAUNCH >/dev/null; then exit 1; else [ "$?" -eq 5 ]; fi
[ "$(grep -c '^broker$' "$tmp/chain.record" 2>/dev/null || true)" -eq "$broker_before" ]
[ -f "$XDG_STATE_HOME/kotak/launch-request.json" ]
cp "$tmp/launch-status.saved" "$tmp/responses/doctor.json"

# The current installed release is re-attested immediately before preflight/launch.
cp "$tmp/release.json" "$tmp/release.saved"
python3 -B - "$tmp/release.json" <<'PY'
import json,sys
p=sys.argv[1]; value=json.load(open(p)); value['source_epoch']+=1
open(p,'w').write(json.dumps(value,sort_keys=True,separators=(',',':'))+'\n')
PY
before=$(grep -c '^BEGIN$' "$tmp/ssh.record")
if "$kotak" shaurya-shadow-launch --confirm SHAURYA_SHADOW_LAUNCH >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
[ "$(grep -c '^BEGIN$' "$tmp/ssh.record")" -eq "$before" ]
cp "$tmp/release.saved" "$tmp/release.json"
: > "$tmp/ssh.record"; : > "$tmp/chain.record"
cp "$XDG_STATE_HOME/kotak/launch-request.json" "$tmp/request.saved"
export FIXTURE_DROP_RESPONSE_ONCE="$tmp/drop-response.once"
if "$kotak" shaurya-shadow-launch --confirm SHAURYA_SHADOW_LAUNCH >/dev/null; then exit 1; else [ "$?" -eq 5 ]; fi
[ -f "$XDG_STATE_HOME/kotak/launch-request.json" ]
printf '%s\n' 'doctor:launch' broker watcher 'cleanup:shaurya-shadow-once@00000000-0000-4000-8000-000000000004.service' > "$tmp/chain.expected"
cmp "$tmp/chain.expected" "$tmp/chain.record"
chain_before=$(wc -l < "$tmp/chain.record")
recovery_now=$(python3 -B - "$tmp/request.saved" <<'PY'
import json,sys
print(json.load(open(sys.argv[1]))['timestamp_ns']+61_000_000_001)
PY
)
first=$(FIXTURE_NOW_NS="$recovery_now" "$kotak" shaurya-shadow-launch --confirm SHAURYA_SHADOW_LAUNCH)
[ "$(wc -l < "$tmp/chain.record")" -eq $((chain_before + 1)) ]
[ "$(tail -n 1 "$tmp/chain.record")" = doctor:launch ]
unset FIXTURE_DROP_RESPONSE_ONCE
[ -f "$tmp/chain/00000000-0000-4000-8000-000000000004.launch.tombstone" ]
[ ! -e "$XDG_STATE_HOME/kotak/launch-request.json" ]
[ -f "$XDG_STATE_HOME/kotak/launch-00000000-0000-4000-8000-000000000004.consumed.json" ]
printf '%s' "$first" | grep -q 'verified=yes'

# A process death after the durable completing tombstone resumes exact cleanup
# without executing the broker or watcher twice, then promotes terminal truth.
FIXTURE_INVOCATION_ID=00000000-0000-4000-8000-000000000010 "$kotak" prepare --confirm SHAURYA_PREPARE >/dev/null
chain_before=$(wc -l < "$tmp/chain.record")
if FIXTURE_REMOTE_POWER_LOSS_POINT=after_completing_tombstone \
   "$kotak" shaurya-shadow-launch --confirm SHAURYA_SHADOW_LAUNCH >/dev/null; then exit 1; else [ "$?" -eq 5 ]; fi
[ -f "$tmp/chain/00000000-0000-4000-8000-000000000010.launch.tombstone" ]
python3 -B - "$tmp/chain/00000000-0000-4000-8000-000000000010.launch.tombstone" <<'PY'
import json,sys
value=json.load(open(sys.argv[1])); assert value["phase"] == "completing" and value["completed_at_ns"] == 0
PY
"$kotak" shaurya-shadow-launch --confirm SHAURYA_SHADOW_LAUNCH | grep -q 'verified=yes'
[ "$(grep -c '^broker$' "$tmp/chain.record")" -eq 2 ]
[ "$(grep -c '^watcher$' "$tmp/chain.record")" -eq 2 ]
[ "$(wc -l < "$tmp/chain.record")" -eq $((chain_before + 5)) ]
python3 -B - "$tmp/chain/00000000-0000-4000-8000-000000000010.launch.tombstone" <<'PY'
import json,sys
value=json.load(open(sys.argv[1])); assert value["phase"] == "completed" and value["completed_at_ns"] > 0
PY
[ ! -e "$tmp/chain/00000000-0000-4000-8000-000000000010.claim.json" ]
[ ! -e "$tmp/chain/00000000-0000-4000-8000-000000000010.result.json" ]

# The public alias traverses the same real fixture launch chain, not only dry-run parsing.
FIXTURE_INVOCATION_ID=00000000-0000-4000-8000-000000000011 "$kotak" prepare --confirm SHAURYA_PREPARE >/dev/null
chain_before=$(wc -l < "$tmp/chain.record")
alias_result=$("$kotak" shadow-launch --confirm SHAURYA_SHADOW_LAUNCH)
printf '%s' "$alias_result" | grep -q 'command=shaurya-shadow-launch status=success code=0 verified=yes'
[ "$(wc -l < "$tmp/chain.record")" -eq $((chain_before + 4)) ]
tail -n 4 "$tmp/chain.record" > "$tmp/alias-chain"
printf '%s\n' doctor:launch broker watcher cleanup:shaurya-shadow-once@00000000-0000-4000-8000-000000000011.service > "$tmp/alias-chain.expected"
cmp "$tmp/alias-chain.expected" "$tmp/alias-chain"

# Replay is refused locally by the immutable consumed tombstone without another SSH attempt.
cp "$tmp/request.saved" "$XDG_STATE_HOME/kotak/launch-request.json"; before=$(grep -c '^BEGIN$' "$tmp/ssh.record")
if "$kotak" shaurya-shadow-launch --confirm SHAURYA_SHADOW_LAUNCH >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
[ "$(grep -c '^BEGIN$' "$tmp/ssh.record")" -eq "$before" ]
rm "$XDG_STATE_HOME/kotak/launch-request.json"

# Removing only the local barrier cannot replay work; the correlated remote terminal result is returned.
rm "$XDG_STATE_HOME/kotak/launch-00000000-0000-4000-8000-000000000004.consumed.json"
cp "$tmp/request.saved" "$XDG_STATE_HOME/kotak/launch-request.json"; before=$(grep -c '^BEGIN$' "$tmp/ssh.record")
"$kotak" shaurya-shadow-launch --confirm SHAURYA_SHADOW_LAUNCH | grep -q 'verified=yes'
[ "$(grep -c '^BEGIN$' "$tmp/ssh.record")" -eq $((before + 1)) ]
[ ! -e "$XDG_STATE_HOME/kotak/launch-request.json" ]

# An expired request is refused locally without SSH.
FIXTURE_NOW_NS=100000000000 FIXTURE_INVOCATION_ID=00000000-0000-4000-8000-000000000009 "$kotak" prepare --confirm SHAURYA_PREPARE >/dev/null
before=$(grep -c '^BEGIN$' "$tmp/ssh.record")
if FIXTURE_NOW_NS=161000000001 "$kotak" preflight >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
[ "$(grep -c '^BEGIN$' "$tmp/ssh.record")" -eq "$before" ]
rm "$XDG_STATE_HOME/kotak/launch-request.json"

# Wrong-instance/malformed watcher evidence is never upgraded to verified success and leaves evidence for diagnosis.
export FIXTURE_WATCH_OVERRIDE='unit_instance="shaurya-shadow-once@00000000-0000-4000-8000-000000000099.service"'
if FIXTURE_INVOCATION_ID=00000000-0000-4000-8000-000000000005 "$kotak" prepare --confirm SHAURYA_PREPARE >/dev/null &&
   "$kotak" shaurya-shadow-launch --confirm SHAURYA_SHADOW_LAUNCH >/dev/null; then exit 1; fi
unset FIXTURE_WATCH_OVERRIDE
rm "$XDG_STATE_HOME/kotak/launch-request.json"

# A claim-root ancestor replacement after creation is detected through the held directory identity.
mkdir "$tmp/foreign-chain"; chmod 700 "$tmp/foreign-chain"; printf foreign > "$tmp/foreign-chain/operator-file"
export FIXTURE_REMOTE_SWAP_POINT=after_attestation_write FIXTURE_REMOTE_SWAP_TARGET="$tmp/foreign-chain"
FIXTURE_INVOCATION_ID=00000000-0000-4000-8000-000000000006 "$kotak" prepare --confirm SHAURYA_PREPARE >/dev/null
if "$kotak" shaurya-shadow-launch --confirm SHAURYA_SHADOW_LAUNCH >/dev/null; then exit 1; fi
[ "$(cat "$tmp/foreign-chain/operator-file")" = foreign ]
rm "$tmp/chain"; mv "$tmp/chain.held" "$tmp/chain"; unset FIXTURE_REMOTE_SWAP_POINT FIXTURE_REMOTE_SWAP_TARGET
rm "$XDG_STATE_HOME/kotak/launch-request.json"

# Replacing a result after its descriptor-bound read cannot cause cleanup to unlink the replacement inode.
printf foreign-result > "$tmp/replacement"; chmod 600 "$tmp/replacement"
export FIXTURE_REMOTE_SWAP_POINT=after_result_read FIXTURE_REMOTE_SWAP_TARGET="$tmp/replacement"
FIXTURE_INVOCATION_ID=00000000-0000-4000-8000-000000000007 "$kotak" prepare --confirm SHAURYA_PREPARE >/dev/null
if "$kotak" shaurya-shadow-launch --confirm SHAURYA_SHADOW_LAUNCH >/dev/null; then exit 1; fi
[ "$(cat "$tmp/chain/00000000-0000-4000-8000-000000000007.result.json")" = foreign-result ]
unset FIXTURE_REMOTE_SWAP_POINT FIXTURE_REMOTE_SWAP_TARGET
rm "$XDG_STATE_HOME/kotak/launch-request.json"

# Start refusal is terminal and never triggers a cleanup start fallback.
export FIXTURE_START_REFUSAL=1
FIXTURE_INVOCATION_ID=00000000-0000-4000-8000-000000000008 "$kotak" prepare --confirm SHAURYA_PREPARE >/dev/null
if "$kotak" shaurya-shadow-launch --confirm SHAURYA_SHADOW_LAUNCH >/dev/null; then exit 1; else [ "$?" -eq 3 ]; fi
unset FIXTURE_START_REFUSAL
rm "$XDG_STATE_HOME/kotak/launch-request.json"

# Unsafe identity bytes or a symlink are rejected before SSH.
before=$(grep -c '^BEGIN$' "$tmp/ssh.record"); chmod 644 "$FIXTURE_SSH_IDENTITY"
if "$kotak" doctor --remote >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
[ "$(grep -c '^BEGIN$' "$tmp/ssh.record")" -eq "$before" ]; chmod 600 "$FIXTURE_SSH_IDENTITY"
mv "$FIXTURE_SSH_IDENTITY" "$tmp/operator-identity.real"; ln -s "$tmp/operator-identity.real" "$FIXTURE_SSH_IDENTITY"
if "$kotak" doctor --remote >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
[ "$(grep -c '^BEGIN$' "$tmp/ssh.record")" -eq "$before" ]
rm "$FIXTURE_SSH_IDENTITY"; mv "$tmp/operator-identity.real" "$FIXTURE_SSH_IDENTITY"

# Swapping the identity pathname after its descriptor is opened is detected before SSH.
cp "$FIXTURE_SSH_IDENTITY" "$tmp/foreign-identity"; chmod 600 "$tmp/foreign-identity"
export FIXTURE_IDENTITY_SWAP_TARGET="$tmp/foreign-identity"; before=$(grep -c '^BEGIN$' "$tmp/ssh.record")
if "$kotak" doctor --remote >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
[ "$(grep -c '^BEGIN$' "$tmp/ssh.record")" -eq "$before" ]
rm "$FIXTURE_SSH_IDENTITY"; mv "$FIXTURE_SSH_IDENTITY.held-$$" "$FIXTURE_SSH_IDENTITY" 2>/dev/null || {
  held=$(find "$XDG_CONFIG_HOME/kotak" -name 'operator_ed25519.held-*' -print -quit); mv "$held" "$FIXTURE_SSH_IDENTITY"
}
unset FIXTURE_IDENTITY_SWAP_TARGET

# Equal-length same-inode overwrites immediately before popen are detected;
# SSH consumes neither the changed source nor a stale snapshot.
cp "$FIXTURE_SSH_IDENTITY" "$tmp/identity.inplace.saved"
export FIXTURE_IDENTITY_INPLACE_MUTATE=1; before=$(grep -c '^BEGIN$' "$tmp/ssh.record")
if "$kotak" doctor --remote >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
[ "$(grep -c '^BEGIN$' "$tmp/ssh.record")" -eq "$before" ]
cmp -s "$FIXTURE_SSH_IDENTITY" "$tmp/identity.inplace.saved" && exit 1
cp "$tmp/identity.inplace.saved" "$FIXTURE_SSH_IDENTITY"; chmod 600 "$FIXTURE_SSH_IDENTITY"
unset FIXTURE_IDENTITY_INPLACE_MUTATE

cp "$XDG_CONFIG_HOME/kotak/known_hosts" "$tmp/known-hosts.inplace.saved"
export FIXTURE_KNOWN_HOSTS_INPLACE_MUTATE=1; before=$(grep -c '^BEGIN$' "$tmp/ssh.record")
if "$kotak" doctor --remote >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
[ "$(grep -c '^BEGIN$' "$tmp/ssh.record")" -eq "$before" ]
cmp -s "$XDG_CONFIG_HOME/kotak/known_hosts" "$tmp/known-hosts.inplace.saved" && exit 1
cp "$tmp/known-hosts.inplace.saved" "$XDG_CONFIG_HOME/kotak/known_hosts"; chmod 600 "$XDG_CONFIG_HOME/kotak/known_hosts"
unset FIXTURE_KNOWN_HOSTS_INPLACE_MUTATE
[ -z "$(find "$tmp/held" -mindepth 1 -print)" ]

# The known-hosts file and operator fingerprint are fixed, protected, and bound to the private key.
chmod 644 "$XDG_CONFIG_HOME/kotak/known_hosts"
if "$kotak" doctor --remote >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
chmod 600 "$XDG_CONFIG_HOME/kotak/known_hosts"
cp "$XDG_CONFIG_HOME/kotak/operator-device.json" "$tmp/operator.saved"
python3 -B - "$XDG_CONFIG_HOME/kotak/operator-device.json" <<'PY'
import json,sys
p=sys.argv[1]; value=json.load(open(p)); value['public_key_fingerprint']='SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
open(p,'w').write(json.dumps(value,sort_keys=True,separators=(',',':'))+'\n')
PY
if "$kotak" doctor --remote >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
cp "$tmp/operator.saved" "$XDG_CONFIG_HOME/kotak/operator-device.json"

# Closed response schema and exact inactive-unit fact are mandatory.
cp "$tmp/responses/status.json" "$tmp/status.saved"
python3 -B - "$tmp/responses/status.json" <<'PY'
import json,sys
p=sys.argv[1];v=json.load(open(p));v['unit_status']='active';open(p,'w').write(json.dumps(v,sort_keys=True,separators=(',',':'))+'\n')
PY
if "$kotak" status >/dev/null; then exit 1; else [ "$?" -eq 5 ]; fi
cp "$tmp/status.saved" "$tmp/responses/status.json"

if "$kotak" doctor --remote --remote >/dev/null; then exit 1; else [ "$?" -eq 2 ]; fi
export FIXTURE_SSH_DELAY=6
if "$kotak" doctor --remote >/dev/null; then exit 1; else [ "$?" -eq 4 ]; fi
unset FIXTURE_SSH_DELAY
printf '%s\n' 'test_kotak_cli: PASS'
