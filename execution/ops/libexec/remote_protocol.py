#!/usr/bin/env python3
"""Closed production protocols for remote inspection and one-shot shadow launch.

Installed entry points always construct ProductionDependencies. Hermetic tests import
the operations and pass explicit fake dependencies from a non-packaged test driver.
There is deliberately no environment or command-line fixture selector here.
"""
from __future__ import annotations

import hashlib, json, os, platform, re, stat, subprocess, sys, time
from pathlib import Path

EXIT_USAGE, EXIT_REFUSAL, EXIT_UNAVAILABLE, EXIT_INTERNAL = 2, 3, 5, 70
UNIT_TEMPLATE = "shaurya-shadow-once@.service"
INSTALL_ROOT = Path("/opt/shaurya")
OPERATOR_ROOT = Path("/var/lib/shaurya-execution/operator")
CLAIM_ROOT = Path("/run/shaurya-execution/claims")
RESULT_ROOT = Path("/run/shaurya-execution/results")
DEPLOYMENT_PATH = Path("/etc/shaurya-execution/deployment.json")
SYSTEMCTL = Path("/usr/bin/systemctl")
FIXED_ENV = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"}
UNIT_PATH = Path("/etc/systemd/system/shaurya-shadow-once@.service")
EXECUTOR_CONFIG = INSTALL_ROOT / "config/executor.json"
EXPECTED_UNIT = ("[Unit]\nDescription=Shaurya one-shot shadow executor %i\n"
                 "ConditionPathExists=/run/shaurya-execution/claims/%i.json\n"
                 "[Service]\nType=exec\nUser=shaurya-execution\nGroup=shaurya-execution\nRestart=no\n"
                 "RuntimeMaxSec=15s\nTimeoutStartSec=15s\nTimeoutStopSec=5s\nKillMode=mixed\n"
                 "ExecStart=/opt/shaurya/bin/shaurya-executor serve --config /opt/shaurya/config/executor.json "
                 "--launch-attestation /run/shaurya-execution/claims/%i.json\n"
                 "NoNewPrivileges=yes\nPrivateTmp=yes\nProtectSystem=strict\nProtectHome=yes\n")
EXPECTED_UNIT_DIGEST = hashlib.sha256(EXPECTED_UNIT.encode("ascii")).hexdigest()
HEX = re.compile(r"[0-9a-f]{64}").fullmatch
COMMIT = re.compile(r"[0-9a-f]{40}").fullmatch
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}").fullmatch
ID = re.compile(r"[A-Za-z0-9._-]{1,64}").fullmatch

DEPLOYMENT_FIELDS = {"schema_version", "deployment_version", "compatibility_version", "ssh_host_alias",
                     "expected_remote_os", "expected_remote_architecture", "executor_commit",
                     "executor_source_tree_sha256", "executor_build_digest", "deployment_manifest_digest",
                     "remote_installation_root", "auth_helper_path", "auth_helper_digest",
                     "doctor_helper_path", "doctor_helper_digest", "broker_helper_path", "broker_helper_digest",
                     "protocol_helper_path", "protocol_helper_digest", "watcher_path", "watcher_digest",
                     "orchestration_unit", "unit_template_digest", "protocol_versions", "timeouts"}
STATUS_FIELDS = {"status", "remote_os", "remote_architecture", "executor_commit", "executor_source_state",
                 "executor_source_tree_sha256", "executor_build_digest",
                 "deployment_digest", "live_gate", "unit_status", "timer_present", "protocol_versions",
                 "auth_helper_digest", "doctor_helper_digest", "broker_helper_digest", "protocol_helper_digest", "watcher_digest",
                 "orchestration_unit", "unit_template_digest", "execution_session_id"}
REQUEST_FIELDS = {"schema_version", "invocation_id", "timestamp_ns", "operator_id", "device_id",
                  "public_key_fingerprint", "release_digest", "deployment_digest", "mode", "confirmation_type"}
ATTESTATION_FIELDS = {"schema_version", "cli_release_digest", "confirmation_type", "deployment_manifest_digest",
                      "device_id", "executor_build_digest", "execution_session_id", "invocation_id",
                      "launch_timestamp_ns", "operator_id", "public_key_fingerprint", "requested_mode"}
CLAIM_FIELDS = {"schema_version", "claim_id", "expires_at_ns", "peer_digest", "executable_digest",
                "config_digest", "orchestration_unit", "unit_instance", "attestation_path",
                "attestation_digest", "executor_config_path", "execution_session_id"}
RUNTIME_FIELDS = {"peer_digest", "executable_digest", "config_digest", "orchestration_unit", "unit_pinned",
                  "live_gate", "replay", "executor_config_path", "launch_attestation_path",
                  "launch_attestation_digest", "execution_session_id"}
WATCH_FIELDS = {"invocation_id", "unit_instance", "attestation_digest", "execution_session_id",
                "executor_build_digest", "restart", "persistent_timer", "ready", "peers_ready",
                "observation_fresh", "attested", "ledger_ready", "claim_consumed", "live_gate"}
LAUNCH_RESPONSE_FIELDS = WATCH_FIELDS | {"status", "timer_present", "cleanup_complete"}
TOMBSTONE_FIELDS = {"schema_version", "phase", "invocation_id", "request_digest", "attestation_digest",
                    "execution_session_id", "unit_instance", "executor_config_path", "config_digest",
                    "completed_at_ns", "response"}


class ProtocolError(Exception):
    def __init__(self, code: int = EXIT_UNAVAILABLE): super().__init__(str(code)); self.code = code


class HeldDirectory:
    def __init__(self, path: Path, private: bool = True):
        self.path = path
        if not path.is_absolute(): raise ProtocolError(EXIT_REFUSAL)
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
        descriptor = os.open("/", flags)
        try:
            for part in path.parts[1:]:
                before = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
                unsafe_write = stat.S_IMODE(before.st_mode) & 0o022
                if (not stat.S_ISDIR(before.st_mode) or before.st_uid not in (0, os.geteuid())
                        or unsafe_write and not (before.st_uid == 0 and before.st_mode & stat.S_ISVTX)):
                    raise ProtocolError(EXIT_REFUSAL)
                child = os.open(part, flags, dir_fd=descriptor); after = os.fstat(child)
                if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino): os.close(child); raise ProtocolError(EXIT_REFUSAL)
                os.close(descriptor); descriptor = child
            opened = os.fstat(descriptor)
            if private and stat.S_IMODE(opened.st_mode) & 0o077: raise ProtocolError(EXIT_REFUSAL)
            self.fd = descriptor; descriptor = -1; self.identity = (opened.st_dev, opened.st_ino)
        finally:
            if descriptor >= 0: os.close(descriptor)
    def revalidate(self):
        current = os.stat(self.path, follow_symlinks=False)
        if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != self.identity: raise ProtocolError(EXIT_REFUSAL)
    def close(self):
        if getattr(self, "fd", -1) >= 0: os.close(self.fd); self.fd = -1
    def __enter__(self): return self
    def __exit__(self, *_): self.close()


def safe_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9.-]{1,100}", name) or name in (".", ".."): raise ProtocolError(EXIT_REFUSAL)
    return name


def write_at(root: HeldDirectory, name: str, payload: bytes) -> tuple[int, int]:
    root.revalidate(); flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
    descriptor = os.open(safe_name(name), flags, 0o600, dir_fd=root.fd)
    try:
        view = memoryview(payload)
        while view:
            count = os.write(descriptor, view); view = view[count:]
        os.fsync(descriptor); info = os.fstat(descriptor); os.fsync(root.fd)
        try: root.revalidate()
        except Exception:
            current = os.stat(safe_name(name), dir_fd=root.fd, follow_symlinks=False)
            if (current.st_dev, current.st_ino) == (info.st_dev, info.st_ino): os.unlink(name, dir_fd=root.fd)
            raise
        return info.st_dev, info.st_ino
    finally: os.close(descriptor)


def read_at(root: HeldDirectory, name: str, fields: set[str], maximum: int = 65536) -> tuple[dict, tuple[int, int]]:
    root.revalidate(); flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
    descriptor = os.open(safe_name(name), flags, dir_fd=root.fd)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid not in (0, os.geteuid()) or stat.S_IMODE(info.st_mode) != 0o600 or not 0 < info.st_size <= maximum:
            raise ProtocolError(EXIT_REFUSAL)
        raw = os.read(descriptor, maximum + 1); root.revalidate()
    finally: os.close(descriptor)
    try: value = json.loads(raw.decode("ascii", "strict"), object_pairs_hook=duplicate_free)
    except (UnicodeError, json.JSONDecodeError): raise ProtocolError(EXIT_REFUSAL)
    if not isinstance(value, dict) or set(value) != fields or canonical(value) != raw: raise ProtocolError(EXIT_REFUSAL)
    return value, (info.st_dev, info.st_ino)


def read_optional_at(root: HeldDirectory, name: str, fields: set[str], maximum: int = 65536):
    try: return read_at(root, name, fields, maximum)
    except FileNotFoundError: return None


def unlink_at(root: HeldDirectory, name: str, identity: tuple[int, int]) -> None:
    root.revalidate(); current = os.stat(safe_name(name), dir_fd=root.fd, follow_symlinks=False)
    if not stat.S_ISREG(current.st_mode) or (current.st_dev, current.st_ino) != identity: raise ProtocolError(EXIT_REFUSAL)
    os.unlink(name, dir_fd=root.fd); os.fsync(root.fd)


def replace_at(root: HeldDirectory, name: str, identity: tuple[int, int], payload: bytes) -> tuple[int, int]:
    temporary = f".{safe_name(name)}.{os.getpid()}.{time.time_ns()}"; root.revalidate()
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600, dir_fd=root.fd)
    try:
        view = memoryview(payload)
        while view:
            count = os.write(descriptor, view); view = view[count:]
        os.fsync(descriptor); replacement = os.fstat(descriptor)
    finally: os.close(descriptor)
    try:
        current = os.stat(name, dir_fd=root.fd, follow_symlinks=False)
        if not stat.S_ISREG(current.st_mode) or (current.st_dev, current.st_ino) != identity:
            raise ProtocolError(EXIT_REFUSAL)
        os.replace(temporary, name, src_dir_fd=root.fd, dst_dir_fd=root.fd); os.fsync(root.fd); root.revalidate()
        return replacement.st_dev, replacement.st_ino
    except Exception:
        try: os.unlink(temporary, dir_fd=root.fd)
        except OSError: pass
        raise


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def sha256_fd(descriptor: int) -> str:
    digest = hashlib.sha256(); os.lseek(descriptor, 0, os.SEEK_SET)
    while block := os.read(descriptor, 1024 * 1024): digest.update(block)
    os.lseek(descriptor, 0, os.SEEK_SET); return digest.hexdigest()


def read_fixed_file(path: Path, *, maximum: int = 64 * 1024 * 1024,
                    expected_uid: int | None = 0, exact_mode: int | None = None) -> bytes:
    with HeldDirectory(path.parent, private=False) as parent:
        flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
        descriptor = os.open(path.name, flags, dir_fd=parent.fd)
        try:
            info = os.fstat(descriptor); data = bytearray()
            while block := os.read(descriptor, 1024 * 1024):
                data.extend(block)
                if len(data) > maximum: raise ProtocolError(EXIT_REFUSAL)
            parent.revalidate(); current = os.stat(path.name, dir_fd=parent.fd, follow_symlinks=False)
            if (not stat.S_ISREG(info.st_mode) or expected_uid is not None and info.st_uid != expected_uid
                    or stat.S_IMODE(info.st_mode) & 0o022
                    or exact_mode is not None and stat.S_IMODE(info.st_mode) != exact_mode
                    or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)):
                raise ProtocolError(EXIT_REFUSAL)
            return bytes(data)
        finally: os.close(descriptor)


def digest_fixed_file(path: Path, **kwargs) -> str:
    return hashlib.sha256(read_fixed_file(path, **kwargs)).hexdigest()


def duplicate_free(pairs):
    output = {}
    for key, value in pairs:
        if key in output: raise ProtocolError(EXIT_REFUSAL)
        output[key] = value
    return output


def load_json(path: Path, fields: set[str], maximum: int = 65536) -> dict:
    descriptor = None
    try:
        parent = HeldDirectory(path.parent, private=False)
        flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
        descriptor = os.open(path.name, flags, dir_fd=parent.fd); info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= maximum or info.st_uid not in (0, os.geteuid()) or stat.S_IMODE(info.st_mode) & 0o022:
            raise ProtocolError(EXIT_REFUSAL)
        raw = os.read(descriptor, maximum + 1); parent.revalidate()
        value = json.loads(raw.decode("ascii", "strict"), object_pairs_hook=duplicate_free)
    except ProtocolError: raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error: raise ProtocolError() from error
    finally:
        for opened in (descriptor,):
            if opened is not None:
                try: os.close(opened)
                except OSError: pass
        if 'parent' in locals(): parent.close()
    if not isinstance(value, dict) or set(value) != fields or canonical(value) != raw: raise ProtocolError(EXIT_REFUSAL)
    return value


def load_any_json(path: Path, maximum: int = 65536) -> dict:
    """Read a protected canonical object before applying a caller-specific exact schema."""
    descriptor = None
    try:
        parent = HeldDirectory(path.parent, private=False); file_flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"): file_flags |= os.O_NOFOLLOW
        descriptor = os.open(path.name, file_flags, dir_fd=parent.fd); info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= maximum or info.st_uid not in (0, os.geteuid()) or stat.S_IMODE(info.st_mode) & 0o022:
            raise ProtocolError(EXIT_REFUSAL)
        raw = os.read(descriptor, maximum + 1); parent.revalidate(); value = json.loads(raw.decode("ascii", "strict"), object_pairs_hook=duplicate_free)
    except ProtocolError: raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error: raise ProtocolError() from error
    finally:
        for opened in (descriptor,):
            if opened is not None:
                try: os.close(opened)
                except OSError: pass
        if 'parent' in locals(): parent.close()
    if not isinstance(value, dict) or canonical(value) != raw: raise ProtocolError(EXIT_REFUSAL)
    return value


def load_deployment(path: Path) -> dict:
    value = load_any_json(path)
    if set(value) != DEPLOYMENT_FIELDS or COMMIT(str(value.get("executor_commit", ""))) is None:
        raise ProtocolError(EXIT_REFUSAL)
    if any(HEX(str(value.get(key, ""))) is None for key in (
            "executor_source_tree_sha256", "executor_build_digest", "deployment_manifest_digest")):
        raise ProtocolError(EXIT_REFUSAL)
    recorded = value.get("deployment_manifest_digest")
    unsigned = dict(value); unsigned["deployment_manifest_digest"] = "0" * 64
    digest = hashlib.sha256(canonical(unsigned)).hexdigest()
    if digest != recorded: raise ProtocolError(EXIT_REFUSAL)
    return value


def canonical_deployment_digest(path: Path) -> str:
    return str(load_deployment(path)["deployment_manifest_digest"])


def load_stdin(fields: set[str]) -> dict:
    raw = sys.stdin.buffer.read(65537)
    if not raw or len(raw) > 65536: raise ProtocolError(EXIT_REFUSAL)
    try: value = json.loads(raw.decode("ascii", "strict"), object_pairs_hook=duplicate_free)
    except (UnicodeError, json.JSONDecodeError): raise ProtocolError(EXIT_REFUSAL)
    if not isinstance(value, dict) or set(value) != fields or canonical(value) != raw: raise ProtocolError(EXIT_REFUSAL)
    return value


def valid_status(value: dict, dependencies) -> bool:
    return (set(value) == STATUS_FIELDS and value["status"] == "ok" and value["remote_os"] == dependencies.system()
            and value["remote_architecture"] == dependencies.architecture() and COMMIT(str(value["executor_commit"]))
            and value["executor_source_state"] == "clean" and HEX(str(value["executor_source_tree_sha256"]))
            and value["live_gate"] == "OFF" and value["unit_status"] == "inactive" and value["timer_present"] is False
            and value["orchestration_unit"] == UNIT_TEMPLATE and UUID(str(value["execution_session_id"]))
            and value["unit_template_digest"] == EXPECTED_UNIT_DIGEST
            and isinstance(value["protocol_versions"], dict) and set(value["protocol_versions"]) == {"execution", "operator"}
            and all(HEX(str(value[key])) for key in ("executor_build_digest", "deployment_digest", "auth_helper_digest",
                                                     "doctor_helper_digest", "broker_helper_digest", "protocol_helper_digest", "watcher_digest")))


def valid_request(value: dict, now_ns: int, *, allow_expired_recovery: bool = False) -> bool:
    return (value["schema_version"] == "1.0.0" and UUID(str(value["invocation_id"]))
            and type(value["timestamp_ns"]) is int and value["timestamp_ns"] > 0
            and (allow_expired_recovery or
                 value["timestamp_ns"] <= now_ns + 5_000_000_000 and now_ns - value["timestamp_ns"] <= 60_000_000_000)
            and value["mode"] == "shadow" and value["confirmation_type"] == "SHAURYA_PREPARE"
            and HEX(str(value["release_digest"])) and HEX(str(value["deployment_digest"]))
            and ID(str(value["operator_id"])) and ID(str(value["device_id"]))
            and re.fullmatch(r"SHA256:[A-Za-z0-9+/]{20,88}={0,2}", str(value["public_key_fingerprint"])))


def unit_instance(invocation_id: str) -> str:
    if UUID(invocation_id) is None: raise ProtocolError(EXIT_REFUSAL)
    return f"shaurya-shadow-once@{invocation_id}.service"


def make_attestation(request: dict, status: dict, now_ns: int) -> dict:
    return {"schema_version": "1.0.0", "cli_release_digest": request["release_digest"],
            "confirmation_type": "SHAURYA_SHADOW_LAUNCH", "deployment_manifest_digest": request["deployment_digest"],
            "device_id": request["device_id"], "executor_build_digest": status["executor_build_digest"],
            "execution_session_id": status["execution_session_id"], "invocation_id": request["invocation_id"],
            "launch_timestamp_ns": now_ns, "operator_id": request["operator_id"],
            "public_key_fingerprint": request["public_key_fingerprint"], "requested_mode": "shadow"}


def valid_claim(claim: dict, runtime: dict, now_ns: int) -> bool:
    return (claim["schema_version"] == "1.0.0" and UUID(str(claim["claim_id"]))
            and type(claim["expires_at_ns"]) is int and now_ns < claim["expires_at_ns"]
            and runtime["unit_pinned"] is True and runtime["live_gate"] == "OFF" and runtime["replay"] is False
            and claim["orchestration_unit"] == runtime["orchestration_unit"] == UNIT_TEMPLATE
            and claim["unit_instance"] == unit_instance(claim["claim_id"])
            and all(HEX(str(claim[key])) and claim[key] == runtime[key] for key in ("peer_digest", "executable_digest", "config_digest"))
            and claim["executor_config_path"] == runtime["executor_config_path"]
            and claim["attestation_path"] == runtime["launch_attestation_path"]
            and claim["attestation_digest"] == runtime["launch_attestation_digest"]
            and claim["execution_session_id"] == runtime["execution_session_id"])


def valid_watch(value: dict, claim: dict) -> bool:
    return (set(value) == WATCH_FIELDS and value["invocation_id"] == claim["claim_id"]
            and value["unit_instance"] == claim["unit_instance"] and value["attestation_digest"] == claim["attestation_digest"]
            and value["execution_session_id"] == claim["execution_session_id"]
            and value["executor_build_digest"] == claim["executable_digest"]
            and value["restart"] == "no" and value["persistent_timer"] is False and value["live_gate"] == "OFF"
            and all(value[key] is True for key in {"ready", "peers_ready", "observation_fresh", "attested", "ledger_ready", "claim_consumed"}))


def valid_launch_response(value: dict, request: dict, status: dict) -> bool:
    return (set(value) == LAUNCH_RESPONSE_FIELDS and value["status"] == "ok"
            and value["invocation_id"] == request["invocation_id"]
            and value["unit_instance"] == unit_instance(request["invocation_id"])
            and HEX(str(value["attestation_digest"])) and value["execution_session_id"] == status["execution_session_id"]
            and value["executor_build_digest"] == status["executor_build_digest"]
            and value["restart"] == "no" and value["persistent_timer"] is False
            and value["live_gate"] == "OFF" and value["timer_present"] is False
            and value["cleanup_complete"] is True
            and all(value[key] is True for key in {"ready", "peers_ready", "observation_fresh", "attested",
                                                   "ledger_ready", "claim_consumed"}))


def parse_executor_version(raw: bytes, opened_digest: str) -> tuple[str, str, str, str]:
    matched = re.fullmatch(
        rb"shaurya-executor 0\.1\.0 mode=shadow kotak_live=off commit=([0-9a-f]{40}) "
        rb"source_state=(clean|dirty) source_tree_sha256=([0-9a-f]{64}) build_sha256=([0-9a-f]{64})\n",
        raw)
    if (matched is None or matched.group(2) != b"clean"
            or matched.group(4).decode("ascii") != opened_digest):
        raise ProtocolError(EXIT_UNAVAILABLE)
    return (matched.group(1).decode("ascii"), matched.group(2).decode("ascii"),
            matched.group(3).decode("ascii"), opened_digest)


class ProductionDependencies:
    """Fixed production dependencies; no caller-controlled override surface."""
    def system(self) -> str: return platform.system().lower()
    def architecture(self) -> str: return platform.machine()
    def verify_systemctl(self) -> None:
        info = os.stat(SYSTEMCTL, follow_symlinks=False)
        if (SYSTEMCTL.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or stat.S_IMODE(info.st_mode) & 0o022): raise ProtocolError(EXIT_INTERNAL)
    def executor_version(self) -> tuple[str, str, str, str]:
        path = INSTALL_ROOT / "bin/shaurya-executor"; flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
        with HeldDirectory(path.parent, private=False) as parent:
            descriptor = os.open(path.name, flags, dir_fd=parent.fd)
            try:
                info = os.fstat(descriptor); digest = sha256_fd(descriptor)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
                    raise ProtocolError(EXIT_REFUSAL)
                result = subprocess.run([f"/proc/self/fd/{descriptor}", "version"], pass_fds=(descriptor,),
                                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        timeout=5, check=False, env=FIXED_ENV)
                parent.revalidate(); current = os.stat(path.name, dir_fd=parent.fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino): raise ProtocolError(EXIT_REFUSAL)
            finally: os.close(descriptor)
        if result.returncode: raise ProtocolError(EXIT_REFUSAL)
        return parse_executor_version(result.stdout, digest)
    def verify_unit_template(self) -> None:
        unit_bytes = read_fixed_file(UNIT_PATH, maximum=64 * 1024, exact_mode=0o644)
        if hashlib.sha256(unit_bytes).hexdigest() != EXPECTED_UNIT_DIGEST or unit_bytes != EXPECTED_UNIT.encode("ascii"):
            raise ProtocolError(EXIT_REFUSAL)
        self.verify_systemctl()
        shown = subprocess.run([str(SYSTEMCTL), "show", UNIT_TEMPLATE, "--property=FragmentPath,LoadState,Restart,ActiveState"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               timeout=5, check=False, env=FIXED_ENV)
        expected = f"FragmentPath={UNIT_PATH}\nLoadState=loaded\nRestart=no\nActiveState=inactive\n".encode("ascii")
        if shown.returncode or shown.stdout != expected: raise ProtocolError(EXIT_REFUSAL)
    def status(self) -> dict:
        expected = load_json(OPERATOR_ROOT / "status.json", STATUS_FIELDS); actual = dict(expected)
        actual["remote_os"] = self.system(); actual["remote_architecture"] = self.architecture()
        for key, path in (("auth_helper_digest", INSTALL_ROOT / "libexec/kotak-auth-helper"),
                          ("doctor_helper_digest", INSTALL_ROOT / "libexec/kotak-remote-doctor"),
                          ("broker_helper_digest", INSTALL_ROOT / "libexec/shaurya-session-broker"),
                          ("protocol_helper_digest", INSTALL_ROOT / "libexec/remote_protocol.py"),
                          ("watcher_digest", INSTALL_ROOT / "libexec/shaurya-shadow-watcher")):
            actual[key] = digest_fixed_file(path)
        deployment = load_deployment(DEPLOYMENT_PATH)
        actual["deployment_digest"] = deployment["deployment_manifest_digest"]
        self.verify_unit_template(); actual["unit_template_digest"] = EXPECTED_UNIT_DIGEST
        actual["unit_status"] = "inactive"; actual["orchestration_unit"] = UNIT_TEMPLATE
        actual["protocol_versions"] = {"execution": "1.0.0", "operator": "1.0.0"}
        config = load_any_json(EXECUTOR_CONFIG)
        actual["execution_session_id"] = str(config.get("execution_session_id", ""))
        (actual["executor_commit"], actual["executor_source_state"],
         actual["executor_source_tree_sha256"], actual["executor_build_digest"]) = self.executor_version()
        if (actual["executor_commit"] != deployment["executor_commit"]
                or actual["executor_source_state"] != "clean"
                or actual["executor_source_tree_sha256"] != deployment["executor_source_tree_sha256"]
                or actual["executor_build_digest"] != deployment["executor_build_digest"]):
            raise ProtocolError(EXIT_UNAVAILABLE)
        actual["live_gate"] = "OFF"
        timer = subprocess.run([str(SYSTEMCTL), "list-unit-files", "shaurya-shadow*.timer", "--no-legend", "--plain"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               timeout=5, check=False, env=FIXED_ENV)
        actual["timer_present"] = timer.returncode != 0 or bool(timer.stdout.strip())
        if actual != expected: raise ProtocolError()
        return actual

    def runtime(self, claim: dict, attestation: dict) -> dict:
        self.verify_unit_template()
        config_path = Path(claim["executor_config_path"]); config = load_any_json(config_path)
        if (config.get("launch_attestation_root") != str(self.claim_root())
                or config.get("expected_cli_release_digest") != attestation["cli_release_digest"]
                or config.get("expected_deployment_manifest_digest") != attestation["deployment_manifest_digest"]
                or config.get("expected_executor_build_digest") != attestation["executor_build_digest"]):
            raise ProtocolError(EXIT_REFUSAL)
        return {"peer_digest": attestation["cli_release_digest"],
                "executable_digest": digest_fixed_file(INSTALL_ROOT / "bin/shaurya-executor"),
                "config_digest": hashlib.sha256(canonical(config)).hexdigest(), "orchestration_unit": UNIT_TEMPLATE,
                "unit_pinned": True, "live_gate": "OFF" if config.get("mode") == "shadow" else "ON",
                "replay": config.get("mode") == "replay",
                "executor_config_path": str(config_path),
                "launch_attestation_path": str(Path(config["launch_attestation_root"]) / f"{claim['claim_id']}.json"),
                "launch_attestation_digest": claim["attestation_digest"],
                "execution_session_id": str(config.get("execution_session_id", ""))}

    def bind_executor_config(self, claim_id: str, attestation_path: Path, attestation_digest: str):
        destination = EXECUTOR_CONFIG; config = load_any_json(destination)
        attestation = load_json(attestation_path, ATTESTATION_FIELDS)
        if (attestation_path != self.claim_root() / f"{claim_id}.json"
                or config.get("launch_attestation_root") != str(self.claim_root())
                or config.get("expected_cli_release_digest") != attestation["cli_release_digest"]
                or config.get("expected_deployment_manifest_digest") != attestation["deployment_manifest_digest"]
                or config.get("expected_executor_build_digest") != attestation["executor_build_digest"]):
            raise ProtocolError(EXIT_REFUSAL)
        return destination, hashlib.sha256(canonical(config)).hexdigest()

    def cleanup_config(self, claim_id: str, path: Path, digest: str, allow_missing: bool = False) -> None:
        if claim_id == "" or path != EXECUTOR_CONFIG:
            raise ProtocolError(EXIT_REFUSAL)
        try: observed = digest_fixed_file(path, expected_uid=None)
        except FileNotFoundError:
            if allow_missing: return
            raise
        if observed != digest: raise ProtocolError(EXIT_REFUSAL)

    def verify_sibling(self, component: str, path: Path) -> None:
        key = {"broker": "broker_helper_digest", "watcher": "watcher_digest"}.get(component)
        if key is None or digest_fixed_file(path) != self.status()[key]: raise ProtocolError(EXIT_REFUSAL)

    def run_protocol(self, component: str, arguments: list[str], timeout: int) -> bytes:
        path = INSTALL_ROOT / "libexec/remote_protocol.py"; flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
        with HeldDirectory(path.parent, private=False) as parent:
            descriptor = os.open(path.name, flags, dir_fd=parent.fd)
            try:
                info = os.fstat(descriptor); expected = self.status()["protocol_helper_digest"]
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022
                        or sha256_fd(descriptor) != expected): raise ProtocolError(EXIT_REFUSAL)
                parent.revalidate(); current = os.stat(path.name, dir_fd=parent.fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino): raise ProtocolError(EXIT_REFUSAL)
                process = subprocess.run(["/usr/bin/python3", "-I", "-B", "-S", "-E", f"/dev/fd/{descriptor}", f"--{component}", *arguments],
                                         pass_fds=(descriptor,), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, timeout=timeout, check=False,
                                         env=FIXED_ENV)
                parent.revalidate(); current = os.stat(path.name, dir_fd=parent.fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino): raise ProtocolError(EXIT_REFUSAL)
            finally: os.close(descriptor)
        if process.returncode or len(process.stdout) > 65536: raise ProtocolError()
        return process.stdout

    def run_broker(self, claim_path: Path) -> bytes:
        return self.run_protocol("broker", ["--claim", str(claim_path)], 15)

    def run_watcher(self, claim_path: Path, deadline_ns: int) -> bytes:
        return self.run_protocol("watcher", ["--claim", str(claim_path), "--deadline-ns", str(deadline_ns)], 10)

    def run_auth(self, expected_digest: str) -> bytes:
        path = INSTALL_ROOT / "libexec/kotak-auth-helper"; flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
        with HeldDirectory(path.parent, private=False) as parent:
            descriptor = os.open(path.name, flags, dir_fd=parent.fd)
            try:
                info = os.fstat(descriptor)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022
                        or sha256_fd(descriptor) != expected_digest):
                    raise ProtocolError(EXIT_REFUSAL)
                parent.revalidate(); current = os.stat(path.name, dir_fd=parent.fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino): raise ProtocolError(EXIT_REFUSAL)
                result = subprocess.run(["/bin/sh", f"/dev/fd/{descriptor}"], pass_fds=(descriptor,),
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10,
                                        check=False, env=FIXED_ENV)
                parent.revalidate(); current = os.stat(path.name, dir_fd=parent.fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino): raise ProtocolError(EXIT_REFUSAL)
            finally: os.close(descriptor)
        if result.returncode == EXIT_REFUSAL: raise ProtocolError(EXIT_REFUSAL)
        if result.returncode or len(result.stdout) > 16 * 1024: raise ProtocolError(EXIT_UNAVAILABLE)
        return result.stdout

    def start(self, instance: str) -> None:
        self.verify_systemctl()
        result = subprocess.run([str(SYSTEMCTL), "start", "--no-block", instance], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False, env=FIXED_ENV)
        if result.returncode: raise ProtocolError(EXIT_REFUSAL)

    def cleanup_instance(self, instance: str) -> None:
        self.verify_systemctl()
        result = subprocess.run([str(SYSTEMCTL), "stop", instance], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False, env=FIXED_ENV)
        if result.returncode: raise ProtocolError()

    def result_path(self, claim_id: str) -> Path: return RESULT_ROOT / f"{claim_id}.json"
    def result_root(self) -> Path: return RESULT_ROOT
    def claim_root(self) -> Path: return CLAIM_ROOT
    def now_ns(self) -> int: return time.time_ns()
    def record(self, _component: str) -> None: return
    def adversarial_swap(self, _point: str, _claim: dict | None = None) -> None: return
    def interruption(self, _point: str) -> None: return


def watcher(argv: list[str], dependencies) -> int:
    dependencies.record("watcher")
    if len(argv) != 4 or argv[0] != "--claim" or argv[2] != "--deadline-ns": raise ProtocolError(EXIT_USAGE)
    claim_path = Path(argv[1])
    with HeldDirectory(dependencies.claim_root()) as claims:
        if claim_path.parent != claims.path: raise ProtocolError(EXIT_USAGE)
        claim, _ = read_at(claims, claim_path.name, CLAIM_FIELDS)
    try: deadline = int(argv[3])
    except ValueError: raise ProtocolError(EXIT_USAGE)
    if deadline != claim["expires_at_ns"]: raise ProtocolError(EXIT_REFUSAL)
    result_name = f"{claim['claim_id']}.result.json"
    while dependencies.now_ns() < deadline:
        try:
            with HeldDirectory(dependencies.result_root()) as results:
                evidence, _ = read_at(results, result_name, WATCH_FIELDS)
            break
        except FileNotFoundError: time.sleep(0.05)
    else: raise ProtocolError()
    if not valid_watch(evidence, claim): raise ProtocolError()
    sys.stdout.buffer.write(canonical(evidence)); return 0


def broker(argv: list[str], dependencies) -> int:
    dependencies.record("broker")
    if len(argv) != 2 or argv[0] != "--claim": raise ProtocolError(EXIT_USAGE)
    claim_path = Path(argv[1])
    with HeldDirectory(dependencies.claim_root()) as claims:
        if claim_path.parent != claims.path: raise ProtocolError(EXIT_USAGE)
        claim, claim_identity = read_at(claims, claim_path.name, CLAIM_FIELDS)
        attestation_name = f"{claim['claim_id']}.json"
        attestation, attestation_identity = read_at(claims, attestation_name, ATTESTATION_FIELDS)
        runtime = dependencies.runtime(claim, attestation)
        if set(runtime) != RUNTIME_FIELDS or not valid_claim(claim, runtime, dependencies.now_ns()): raise ProtocolError()
        if (hashlib.sha256(canonical(attestation)).hexdigest() != claim["attestation_digest"]
                or attestation["invocation_id"] != claim["claim_id"]
                or attestation["execution_session_id"] != claim["execution_session_id"]): raise ProtocolError(EXIT_REFUSAL)
        for name, identity in ((claim_path.name, claim_identity), (attestation_name, attestation_identity)):
            current = os.stat(name, dir_fd=claims.fd, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != identity: raise ProtocolError(EXIT_REFUSAL)
        consumed_name = f"{claim['claim_id']}.claim.consumed"
        write_at(claims, consumed_name, canonical({"attestation_digest": claim["attestation_digest"], "claim_id": claim["claim_id"]}))
        dependencies.verify_sibling("watcher", Path(__file__).with_name("shaurya-shadow-watcher"))
        dependencies.start(claim["unit_instance"])
        watched = dependencies.run_watcher(claim_path, claim["expires_at_ns"])
        try: evidence = json.loads(watched.decode("ascii"), object_pairs_hook=duplicate_free)
        except (UnicodeError, json.JSONDecodeError): raise ProtocolError()
        if canonical(evidence) != watched or not valid_watch(evidence, claim): raise ProtocolError()
        current_claim = os.stat(claim_path.name, dir_fd=claims.fd, follow_symlinks=False)
        if (current_claim.st_dev, current_claim.st_ino) != claim_identity: raise ProtocolError(EXIT_REFUSAL)
    sys.stdout.buffer.write(watched); return 0


def write_launch_files(request: dict, status: dict, dependencies, root: HeldDirectory):
    claim_id = request["invocation_id"]
    attestation = make_attestation(request, status, dependencies.now_ns()); attestation_bytes = canonical(attestation)
    attestation_name = f"{claim_id}.json"; attestation_path = root.path / attestation_name
    attestation_identity = write_at(root, attestation_name, attestation_bytes)
    dependencies.adversarial_swap("after_attestation_write")
    config_path, config_digest = dependencies.bind_executor_config(claim_id, attestation_path, hashlib.sha256(attestation_bytes).hexdigest())
    claim = {"schema_version": "1.0.0", "claim_id": claim_id, "expires_at_ns": dependencies.now_ns() + 10_000_000_000,
             "peer_digest": request["release_digest"], "executable_digest": status["executor_build_digest"],
             "config_digest": config_digest, "orchestration_unit": UNIT_TEMPLATE, "unit_instance": unit_instance(claim_id),
             "attestation_path": str(attestation_path), "attestation_digest": hashlib.sha256(attestation_bytes).hexdigest(),
             "executor_config_path": str(config_path), "execution_session_id": status["execution_session_id"]}
    claim_name = f"{claim_id}.claim.json"; claim_path = root.path / claim_name
    claim_identity = write_at(root, claim_name, canonical(claim))
    dependencies.adversarial_swap("after_claim_write", claim)
    return claim, claim_path, claim_identity, attestation_path, attestation_identity


def cleanup_launch(claim: dict, claim_path: Path, claim_identity, attestation_path: Path, attestation_identity,
                   dependencies, claims: HeldDirectory, results: HeldDirectory, result_identity) -> None:
    consumed_name = f"{claim['claim_id']}.claim.consumed"; _, consumed_identity = read_at(
        claims, consumed_name, {"attestation_digest", "claim_id"})
    unlink_at(claims, consumed_name, consumed_identity)
    unlink_at(results, f"{claim['claim_id']}.result.json", result_identity)
    unlink_at(claims, claim_path.name, claim_identity); unlink_at(claims, attestation_path.name, attestation_identity)
    dependencies.cleanup_config(claim["claim_id"], Path(claim["executor_config_path"]), claim["config_digest"])


def finish_recovered_cleanup(claims: HeldDirectory, tombstone: dict, dependencies) -> None:
    claim_id = tombstone["invocation_id"]
    claim_name = f"{claim_id}.claim.json"; attestation_name = f"{claim_id}.json"
    consumed_name = f"{claim_id}.claim.consumed"; result_name = f"{claim_id}.result.json"
    claim_item = read_optional_at(claims, claim_name, CLAIM_FIELDS)
    if claim_item is not None:
        claim, claim_identity = claim_item
        if (claim["claim_id"] != claim_id or claim["unit_instance"] != tombstone["unit_instance"]
                or claim["attestation_digest"] != tombstone["attestation_digest"]
                or claim["execution_session_id"] != tombstone["execution_session_id"]
                or claim["executor_config_path"] != tombstone["executor_config_path"]
                or claim["config_digest"] != tombstone["config_digest"]):
            raise ProtocolError(EXIT_REFUSAL)
    attestation_item = read_optional_at(claims, attestation_name, ATTESTATION_FIELDS)
    if attestation_item is not None:
        attestation, attestation_identity = attestation_item
        if (attestation["invocation_id"] != claim_id
                or attestation["execution_session_id"] != tombstone["execution_session_id"]
                or hashlib.sha256(canonical(attestation)).hexdigest() != tombstone["attestation_digest"]):
            raise ProtocolError(EXIT_REFUSAL)
    consumed_item = read_optional_at(claims, consumed_name, {"attestation_digest", "claim_id"})
    if consumed_item is not None:
        consumed, consumed_identity = consumed_item
        if consumed != {"attestation_digest": tombstone["attestation_digest"], "claim_id": claim_id}:
            raise ProtocolError(EXIT_REFUSAL)
    with HeldDirectory(dependencies.result_root()) as results:
        result_item = read_optional_at(results, result_name, WATCH_FIELDS)
        if result_item is not None:
            result, result_identity = result_item
            expected = {key: tombstone["response"][key] for key in WATCH_FIELDS}
            if result != expected: raise ProtocolError(EXIT_REFUSAL)
            unlink_at(results, result_name, result_identity)
    if consumed_item is not None: unlink_at(claims, consumed_name, consumed_identity)
    if claim_item is not None: unlink_at(claims, claim_name, claim_identity)
    if attestation_item is not None: unlink_at(claims, attestation_name, attestation_identity)
    dependencies.cleanup_config(claim_id, Path(tombstone["executor_config_path"]), tombstone["config_digest"], allow_missing=True)


def recovered_launch_response(claims: HeldDirectory, request: dict, status: dict, dependencies) -> dict | None:
    name = f"{request['invocation_id']}.launch.tombstone"
    try: tombstone, tombstone_identity = read_at(claims, name, TOMBSTONE_FIELDS)
    except FileNotFoundError: return None
    response = tombstone.get("response")
    if (tombstone["schema_version"] != "1.0.0" or tombstone["invocation_id"] != request["invocation_id"]
            or tombstone["request_digest"] != hashlib.sha256(canonical(request)).hexdigest()
            or not isinstance(response, dict) or tombstone["attestation_digest"] != response.get("attestation_digest")
            or tombstone["execution_session_id"] != response.get("execution_session_id")):
        raise ProtocolError(EXIT_REFUSAL)
    if (tombstone["unit_instance"] != unit_instance(request["invocation_id"])
            or not isinstance(tombstone["executor_config_path"], str)
            or not HEX(str(tombstone["config_digest"]))):
        raise ProtocolError(EXIT_REFUSAL)
    if not valid_launch_response(response, request, status): raise ProtocolError(EXIT_REFUSAL)
    if tombstone["phase"] == "completing" and tombstone["completed_at_ns"] == 0:
        dependencies.cleanup_instance(tombstone["unit_instance"])
        dependencies.interruption("recovery_after_instance_cleanup")
        finish_recovered_cleanup(claims, tombstone, dependencies)
        completed = dict(tombstone); completed["phase"] = "completed"; completed["completed_at_ns"] = dependencies.now_ns()
        replace_at(claims, name, tombstone_identity, canonical(completed))
        return response
    if tombstone["phase"] != "completed" or type(tombstone["completed_at_ns"]) is not int or tombstone["completed_at_ns"] <= 0:
        raise ProtocolError(EXIT_UNAVAILABLE)
    return response


def doctor(argv: list[str], dependencies) -> int:
    if len(argv) != 1 or argv[0] not in {"auth", "doctor", "status", "preflight", "launch"}: raise ProtocolError(EXIT_USAGE)
    operation = argv[0]; dependencies.record("doctor:" + operation); status = dependencies.status()
    if not valid_status(status, dependencies): raise ProtocolError()
    if operation == "auth":
        response = dependencies.run_auth(status["auth_helper_digest"])
        try: value = json.loads(response.decode("ascii"), object_pairs_hook=duplicate_free)
        except (UnicodeError, json.JSONDecodeError): raise ProtocolError(EXIT_UNAVAILABLE)
        if (canonical(value) != response or set(value) != {"diagnostic_ok", "status"}
                or value["diagnostic_ok"] is not True or value["status"] != "synthetic_transport_only"):
            raise ProtocolError(EXIT_UNAVAILABLE)
        sys.stdout.buffer.write(response); return 0
    request = None
    if operation in {"preflight", "launch"}:
        request = load_stdin(REQUEST_FIELDS)
        if (not valid_request(request, dependencies.now_ns(), allow_expired_recovery=operation == "launch")
                or request["deployment_digest"] != status["deployment_digest"]): raise ProtocolError(EXIT_REFUSAL)
    if operation != "launch": sys.stdout.buffer.write(canonical(status)); return 0
    with HeldDirectory(dependencies.claim_root()) as claims:
        recovered = recovered_launch_response(claims, request, status, dependencies)
        if recovered is not None: sys.stdout.buffer.write(canonical(recovered)); return 0
        if not valid_request(request, dependencies.now_ns()): raise ProtocolError(EXIT_REFUSAL)
        claim, claim_path, claim_identity, attestation_path, attestation_identity = write_launch_files(request, status, dependencies, claims)
        stopped = False
        try:
            dependencies.verify_sibling("broker", Path(__file__).with_name("shaurya-session-broker"))
            result = dependencies.run_broker(claim_path)
            try: evidence = json.loads(result.decode("ascii"), object_pairs_hook=duplicate_free)
            except (UnicodeError, json.JSONDecodeError): raise ProtocolError()
            if canonical(evidence) != result or not valid_watch(evidence, claim): raise ProtocolError()
            with HeldDirectory(dependencies.result_root()) as results:
                factual, result_identity = read_at(results, f"{claim['claim_id']}.result.json", WATCH_FIELDS)
                if factual != evidence: raise ProtocolError(EXIT_REFUSAL)
                dependencies.adversarial_swap("after_result_read", claim)
                response = dict(evidence); response.update({"status": "ok", "timer_present": False, "cleanup_complete": True})
                tombstone = {"schema_version": "1.0.0", "phase": "completing", "invocation_id": claim["claim_id"],
                             "request_digest": hashlib.sha256(canonical(request)).hexdigest(),
                             "attestation_digest": claim["attestation_digest"], "execution_session_id": claim["execution_session_id"],
                             "unit_instance": claim["unit_instance"], "executor_config_path": claim["executor_config_path"],
                             "config_digest": claim["config_digest"],
                             "completed_at_ns": 0, "response": response}
                tombstone_name = f"{claim['claim_id']}.launch.tombstone"
                tombstone_identity = write_at(claims, tombstone_name, canonical(tombstone))
                dependencies.interruption("after_completing_tombstone")
                dependencies.cleanup_instance(claim["unit_instance"]); stopped = True
                cleanup_launch(claim, claim_path, claim_identity, attestation_path, attestation_identity,
                               dependencies, claims, results, result_identity)
                completed = dict(tombstone); completed["phase"] = "completed"; completed["completed_at_ns"] = dependencies.now_ns()
                replace_at(claims, tombstone_name, tombstone_identity, canonical(completed))
        finally:
            if not stopped:
                dependencies.cleanup_instance(claim["unit_instance"])
    sys.stdout.buffer.write(canonical(response)); return 0


def main(dependencies=None) -> int:
    dependencies = dependencies or ProductionDependencies()
    component = sys.argv[1] if len(sys.argv) > 1 else ""
    arguments = sys.argv[2:]
    try:
        if component == "--doctor": return doctor(arguments, dependencies)
        if component == "--broker": return broker(arguments, dependencies)
        if component == "--watcher": return watcher(arguments, dependencies)
        raise ProtocolError(EXIT_INTERNAL)
    except ProtocolError as error: return error.code
    except Exception: return EXIT_INTERNAL


if __name__ == "__main__": raise SystemExit(main())
