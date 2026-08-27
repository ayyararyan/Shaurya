#!/usr/bin/env python3
"""Hermetic-capable Shaurya operator CLI and release lifecycle implementation."""
from __future__ import annotations

import argparse
import base64
import fcntl
import getpass
import gzip
import hashlib
import io
import json
import os
import platform
import pwd
import re
import selectors
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from pathlib import Path, PurePosixPath

VERSION = "1.0.0"
COMPATIBILITY = "1"
EXIT_SUCCESS, EXIT_USAGE, EXIT_REFUSAL, EXIT_TIMEOUT, EXIT_UNAVAILABLE, EXIT_INTERNAL = 0, 2, 3, 4, 5, 70
ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
HEX_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
MARKER_VALUE_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class OpsError(Exception):
    def __init__(self, code: str, exit_code: int = EXIT_USAGE):
        super().__init__(code)
        self.code = code
        self.exit_code = exit_code


class ClosedParser(argparse.ArgumentParser):
    def __init__(self): super().__init__(add_help=False, allow_abbrev=False)
    def error(self, _message): raise OpsError("arguments")
    def exit(self, _status=0, _message=None): raise OpsError("arguments")


class ProductionDependencies:
    """Fixed installed dependencies. Tests pass a separate object by direct import."""
    ssh_path = "/usr/bin/ssh"
    def child_environment(self) -> dict[str, str]:
        return {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"}
    def run(self, argv, **kwargs): return subprocess.run(argv, **kwargs)
    def popen(self, argv, **kwargs): return subprocess.Popen(argv, **kwargs)
    def adversarial_swap(self, _path: Path, _point: str) -> None: return
    def interruption(self, _point: str) -> None: return
    def release_manifest_path(self, default: Path) -> Path: return default
    def new_invocation_id(self) -> str: return str(uuid.uuid4())
    def now_ns(self) -> int: return time.time_ns()
    def ssh_identity_path(self) -> Path:
        home = Path(os.environ.get("HOME", "")); root = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
        return root / "kotak/operator_ed25519"
    def ssh_known_hosts_path(self) -> Path:
        home = Path(os.environ.get("HOME", "")); root = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
        return root / "kotak/known_hosts"
    def transport_snapshot_root(self) -> Path: return Path("/private/tmp")
    def identity_public_key(self, descriptor: int) -> bytes:
        validate_system_command(Path("/usr/bin/ssh-keygen"))
        result = subprocess.run(["/usr/bin/ssh-keygen", "-y", "-f", f"/dev/fd/{descriptor}"],
                                pass_fds=(descriptor,), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=5, check=False,
                                env=self.child_environment())
        if result.returncode or not 0 < len(result.stdout) <= 16 * 1024:
            raise OpsError("ssh_identity_unreadable", EXIT_USAGE)
        os.lseek(descriptor, 0, os.SEEK_SET)
        return result.stdout
    def local_platform(self) -> str: return platform.system().lower()
    def local_architecture(self) -> str: return platform.machine().lower()
    def required_local_commands(self) -> tuple[str, ...]:
        return ("/bin/sh", "/usr/bin/python3", "/usr/bin/ssh", "/usr/bin/ssh-keygen")
    def release_version(self) -> str: return VERSION
    def attest_release(self, path: Path) -> dict: return attest_installed_release(path)
    def source_revision(self, source_root: Path) -> str:
        validate_system_command(Path("/usr/bin/git"))
        result = self.run(["/usr/bin/git", "-C", str(source_root), "rev-parse", "--verify", "HEAD"],
                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          timeout=5, check=False, env=self.child_environment())
        try: revision = result.stdout.decode("ascii", "strict").removesuffix("\n")
        except UnicodeError as error: raise OpsError("source_revision_unverified", EXIT_REFUSAL) from error
        if result.returncode or COMMIT_RE.fullmatch(revision) is None or result.stdout != f"{revision}\n".encode("ascii"):
            raise OpsError("source_revision_unverified", EXIT_REFUSAL)
        return revision


class TerminalDependencies:
    def open(self) -> int: return os.open("/dev/tty", os.O_RDWR | os.O_CLOEXEC)
    def disable_echo(self, descriptor: int):
        import termios
        old = termios.tcgetattr(descriptor); new = old.copy(); new[3] &= ~termios.ECHO
        termios.tcsetattr(descriptor, termios.TCSANOW, new); return old
    def restore_echo(self, descriptor: int, state) -> None:
        import termios
        termios.tcsetattr(descriptor, termios.TCSANOW, state)
    def write_prompt(self, descriptor: int) -> None: os.write(descriptor, b"Synthetic six-digit diagnostic code: ")
    def read_byte(self, descriptor: int) -> bytes: return os.read(descriptor, 1)
    def write_newline(self, descriptor: int) -> None: os.write(descriptor, b"\n")
    def close(self, descriptor: int) -> None: os.close(descriptor)


def open_secure_directory(path: Path, *, create: bool, private_leaf: bool = True) -> tuple[int, tuple[int, int]]:
    """Open an absolute directory without following symlinks and retain its inode."""
    if not path.is_absolute(): raise OpsError("unsafe_local_directory", EXIT_REFUSAL)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
    descriptor = os.open("/", flags)
    try:
        for part in path.parts[1:]:
            try:
                before = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                if not create: raise
                os.mkdir(part, 0o700, dir_fd=descriptor)
                before = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
            mode = stat.S_IMODE(before.st_mode)
            if not stat.S_ISDIR(before.st_mode): raise OpsError("unsafe_local_directory", EXIT_REFUSAL)
            if before.st_uid == os.geteuid():
                if mode & 0o022: raise OpsError("unsafe_local_directory", EXIT_REFUSAL)
            elif before.st_uid == 0:
                if mode & 0o022 and not (before.st_mode & stat.S_ISVTX):
                    raise OpsError("unsafe_local_directory", EXIT_REFUSAL)
            else:
                raise OpsError("unsafe_local_directory", EXIT_REFUSAL)
            child = os.open(part, flags, dir_fd=descriptor)
            after = os.fstat(child)
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                os.close(child); raise OpsError("unsafe_local_directory", EXIT_REFUSAL)
            os.close(descriptor); descriptor = child
        leaf = os.fstat(descriptor)
        if private_leaf and (leaf.st_uid != os.geteuid() or stat.S_IMODE(leaf.st_mode) & 0o077):
            raise OpsError("unsafe_local_directory", EXIT_REFUSAL)
        return descriptor, (leaf.st_dev, leaf.st_ino)
    except Exception:
        os.close(descriptor)
        raise


def verify_open_directory(path: Path, identity: tuple[int, int]) -> None:
    current = os.stat(path, follow_symlinks=False)
    if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != identity:
        raise OpsError("directory_identity_changed", EXIT_REFUSAL)


def open_directory_at(parent_fd: int, name: str, *, create: bool = False, mode: int = 0o700) -> tuple[int, tuple[int, int]]:
    if not name or name in (".", "..") or "/" in name: raise OpsError("unsafe_child_name", EXIT_REFUSAL)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
    if create:
        try: os.mkdir(name, mode, dir_fd=parent_fd)
        except FileExistsError: pass
    before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if not stat.S_ISDIR(before.st_mode) or before.st_uid != os.geteuid() or stat.S_IMODE(before.st_mode) & 0o022:
        raise OpsError("unsafe_child_directory", EXIT_REFUSAL)
    descriptor = os.open(name, flags, dir_fd=parent_fd); after = os.fstat(descriptor)
    if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino): os.close(descriptor); raise OpsError("directory_identity_changed", EXIT_REFUSAL)
    return descriptor, (after.st_dev, after.st_ino)


def open_nested_directory(root_fd: int, parts: tuple[str, ...], *, create: bool) -> int:
    descriptor = os.dup(root_fd)
    try:
        for part in parts:
            child, _ = open_directory_at(descriptor, part, create=create)
            os.close(descriptor); descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor); raise


def regular_digest_at(root_fd: int, relative: str) -> tuple[os.stat_result, str]:
    pure = PurePosixPath(relative); parent_fd = open_nested_directory(root_fd, pure.parts[:-1], create=False)
    try:
        flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
        descriptor = os.open(pure.parts[-1], flags, dir_fd=parent_fd)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid(): raise OpsError("unsafe_release_file", EXIT_REFUSAL)
            return info, sha256_fd(descriptor)
        finally: os.close(descriptor)
    finally: os.close(parent_fd)


def observed_tree(root_fd: int, prefix: str = "") -> set[str]:
    output: set[str] = set()
    with os.scandir(root_fd) as entries:
        for entry in entries:
            name = f"{prefix}/{entry.name}" if prefix else entry.name; info = entry.stat(follow_symlinks=False)
            if stat.S_ISREG(info.st_mode): output.add(name)
            elif stat.S_ISDIR(info.st_mode):
                child, _ = open_directory_at(root_fd, entry.name, create=False)
                try: output.update(observed_tree(child, name))
                finally: os.close(child)
            else: output.add(name)
    return output


def marker(command: str, status: str, code: int, verified: str) -> str:
    values = {"command": command, "status": status, "code": str(code), "verified": verified}
    if any(not MARKER_VALUE_RE.fullmatch(value) for value in values.values()):
        raise OpsError("marker_integrity", EXIT_INTERNAL)
    return "[KOTAK_RESULT] " + " ".join(f"{key}={value}" for key, value in values.items())


def emit(command: str, status: str, code: int, verified: str = "no") -> int:
    print(marker(command, status, code, verified))
    return code


def emit_audited(command: str, status: str, code: int, verified: str = "no") -> int:
    line = marker(command, status, code, verified)
    try:
        _, state, _ = config_paths(); logs = state / "logs"
        logs_fd, _ = open_secure_directory(logs, create=True)
        invocation = str(uuid.uuid4())
        destination = f"{command}-{invocation}.log"
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
        descriptor = os.open(destination, flags, 0o600, dir_fd=logs_fd)
        with os.fdopen(descriptor, "w", encoding="ascii") as output:
            output.write(line + "\n"); output.flush(); os.fsync(output.fileno())
        os.close(logs_fd)
    except (OSError, UnicodeError, OpsError):
        try: os.close(logs_fd)
        except (NameError, OSError): pass
        return emit(command, "audit_integrity_failure", EXIT_INTERNAL)
    print(line)
    return code


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def wipe_bytearray(value: bytearray) -> None:
    for index in range(len(value)): value[index] = 0


def sha256_fd(descriptor: int) -> str:
    digest = hashlib.sha256(); os.lseek(descriptor, 0, os.SEEK_SET)
    while block := os.read(descriptor, 1024 * 1024): digest.update(block)
    os.lseek(descriptor, 0, os.SEEK_SET); return digest.hexdigest()


def canonical_uuid(value: str) -> bool:
    try: parsed = uuid.UUID(value)
    except (ValueError, AttributeError): return False
    return str(parsed) == value and value[14] == "4" and value[19] in "89ab"


def strict_json(path: Path, required: set[str], maximum: int = 64 * 1024,
                exact_mode: int | None = None) -> dict:
    path = Path(os.path.abspath(path))
    parent_fd = None
    try:
        parent_fd, parent_identity = open_secure_directory(path.parent, create=False, private_leaf=False)
        flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
        descriptor = os.open(path.name, flags, dir_fd=parent_fd)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            raw = stream.read(maximum + 1)
        verify_open_directory(path.parent, parent_identity)
        current = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise OpsError("manifest_file_changed", EXIT_REFUSAL)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) & 0o022
                or exact_mode is not None and stat.S_IMODE(info.st_mode) != exact_mode):
            raise OpsError("manifest_file_unsafe")
    except OSError as error:
        raise OpsError("manifest_unreadable") from error
    finally:
        if parent_fd is not None: os.close(parent_fd)
    if not raw or len(raw) > maximum or raw.startswith(b"\xef\xbb\xbf"):
        raise OpsError("manifest_size_or_encoding")
    try:
        text = raw.decode("utf-8", "strict")
        value = json.loads(text, object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError, OpsError) as error:
        raise OpsError("manifest_malformed") from error
    if not isinstance(value, dict) or set(value) != required:
        raise OpsError("manifest_schema")
    if canonical(value) != raw:
        raise OpsError("manifest_not_canonical")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise OpsError("manifest_duplicate_field")
        value[key] = item
    return value


def strict_json_at(parent_fd: int, name: str, required: set[str], maximum: int = 64 * 1024,
                   exact_mode: int | None = None) -> tuple[dict, tuple[int, int]]:
    if not name or name in (".", "..") or "/" in name: raise OpsError("manifest_file_unsafe", EXIT_REFUSAL)
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
        try: info = os.fstat(descriptor); raw = os.read(descriptor, maximum + 1)
        finally: os.close(descriptor)
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as error: raise OpsError("manifest_unreadable") from error
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o022
            or exact_mode is not None and stat.S_IMODE(info.st_mode) != exact_mode
            or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)
            or not raw or len(raw) > maximum or raw.startswith(b"\xef\xbb\xbf")):
        raise OpsError("manifest_file_unsafe", EXIT_REFUSAL)
    try: value = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError, OpsError) as error: raise OpsError("manifest_malformed") from error
    if not isinstance(value, dict) or set(value) != required or canonical(value) != raw:
        raise OpsError("manifest_schema", EXIT_REFUSAL)
    return value, (info.st_dev, info.st_ino)


def atomic_private_json_at(parent_fd: int, name: str, value: object) -> None:
    temporary = f".{name}.{uuid.uuid4()}"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600, dir_fd=parent_fd)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(canonical(value)); output.flush(); os.fsync(output.fileno())
        os.replace(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd); os.fsync(parent_fd)
    except Exception:
        try: os.unlink(temporary, dir_fd=parent_fd)
        except OSError: pass
        raise


def atomic_symlink_at(parent_fd: int, name: str, target: str | None) -> None:
    temporary = f".{name}.{uuid.uuid4()}"
    try:
        if target is None:
            try: os.unlink(name, dir_fd=parent_fd)
            except FileNotFoundError: pass
        else:
            os.symlink(target, temporary, dir_fd=parent_fd)
            os.replace(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.fsync(parent_fd)
    except Exception:
        try: os.unlink(temporary, dir_fd=parent_fd)
        except OSError: pass
        raise


def unlink_exact_regular_at(parent_fd: int, name: str, identity: tuple[int, int] | None = None) -> None:
    before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid(): raise OpsError("unsafe_unlink", EXIT_REFUSAL)
    if identity is not None and (before.st_dev, before.st_ino) != identity: raise OpsError("unsafe_unlink", EXIT_REFUSAL)
    os.unlink(name, dir_fd=parent_fd); os.fsync(parent_fd)


def unlink_exact_symlink_at(parent_fd: int, name: str, target: str) -> None:
    before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if not stat.S_ISLNK(before.st_mode) or os.readlink(name, dir_fd=parent_fd) != target:
        raise OpsError("unsafe_unlink", EXIT_USAGE)
    os.unlink(name, dir_fd=parent_fd); os.fsync(parent_fd)


DEPLOYMENT_FIELDS = {
    "schema_version", "deployment_version", "compatibility_version", "ssh_host_alias",
    "expected_remote_os", "expected_remote_architecture", "executor_commit",
    "executor_source_tree_sha256", "executor_build_digest", "deployment_manifest_digest", "remote_installation_root",
    "auth_helper_path", "auth_helper_digest", "doctor_helper_path", "doctor_helper_digest",
    "broker_helper_path", "broker_helper_digest", "protocol_helper_path", "protocol_helper_digest",
    "watcher_path", "watcher_digest", "orchestration_unit", "unit_template_digest", "protocol_versions", "timeouts",
}
OPERATOR_FIELDS = {"schema_version", "operator_id", "device_id", "public_key_fingerprint"}
RELEASE_FIELDS = {"schema_version", "release_version", "compatibility_version", "source_commit", "source_epoch", "archive_digest", "files"}
LAUNCH_REQUEST_FIELDS = {"schema_version", "invocation_id", "timestamp_ns", "operator_id", "device_id",
                         "public_key_fingerprint", "release_digest", "deployment_digest", "mode", "confirmation_type"}


def validate_abs_remote(value: object) -> str:
    if (not isinstance(value, str) or len(value) > 256
            or re.fullmatch(r"/(?:[A-Za-z0-9._-]+/)*[A-Za-z0-9._-]+", value) is None):
        raise OpsError("manifest_remote_path")
    parts = PurePosixPath(value).parts
    if any(part in (".", "..") for part in parts):
        raise OpsError("manifest_remote_path")
    return value


def validate_deployment(path: Path) -> dict:
    data = strict_json(path, DEPLOYMENT_FIELDS)
    scalar_ids = ("schema_version", "deployment_version", "compatibility_version", "ssh_host_alias",
                  "expected_remote_os", "expected_remote_architecture")
    if any(not isinstance(data[key], str) or not ID_RE.fullmatch(data[key]) for key in scalar_ids):
        raise OpsError("deployment_identifier")
    if data["schema_version"] != "1.0.0" or data["compatibility_version"] != COMPATIBILITY:
        raise OpsError("deployment_version")
    if data["orchestration_unit"] != "shaurya-shadow-once@.service":
        raise OpsError("deployment_orchestration_unit")
    fixed_paths = {"remote_installation_root": "/opt/shaurya",
                   "auth_helper_path": "/opt/shaurya/libexec/kotak-auth-helper",
                   "doctor_helper_path": "/opt/shaurya/libexec/kotak-remote-doctor",
                   "broker_helper_path": "/opt/shaurya/libexec/shaurya-session-broker",
                   "protocol_helper_path": "/opt/shaurya/libexec/remote_protocol.py",
                   "watcher_path": "/opt/shaurya/libexec/shaurya-shadow-watcher"}
    if any(data[key] != expected for key, expected in fixed_paths.items()):
        raise OpsError("deployment_fixed_path")
    if str(data["ssh_host_alias"]).startswith("-"):
        raise OpsError("deployment_host_alias")
    if not COMMIT_RE.fullmatch(str(data["executor_commit"])):
        raise OpsError("deployment_commit")
    for key in ("executor_source_tree_sha256", "executor_build_digest", "auth_helper_digest", "doctor_helper_digest", "broker_helper_digest", "protocol_helper_digest", "watcher_digest", "unit_template_digest", "deployment_manifest_digest"):
        if not HEX_RE.fullmatch(str(data[key])):
            raise OpsError("deployment_digest")
    for key in ("remote_installation_root", "auth_helper_path", "doctor_helper_path", "broker_helper_path", "protocol_helper_path", "watcher_path"):
        validate_abs_remote(data[key])
    protocols = data["protocol_versions"]
    timeouts = data["timeouts"]
    if not isinstance(protocols, dict) or set(protocols) != {"execution", "operator"} or any(not ID_RE.fullmatch(str(x)) for x in protocols.values()):
        raise OpsError("deployment_protocols")
    if not isinstance(timeouts, dict) or set(timeouts) != {"connect_seconds", "operation_seconds", "server_alive_seconds"}:
        raise OpsError("deployment_timeouts")
    if any(type(value) is not int or value < 1 or value > 60 for value in timeouts.values()):
        raise OpsError("deployment_timeouts")
    unsigned = dict(data)
    unsigned["deployment_manifest_digest"] = "0" * 64
    if sha256_bytes(canonical(unsigned)) != data["deployment_manifest_digest"]:
        raise OpsError("deployment_digest_mismatch")
    return data


def validate_operator(path: Path) -> dict:
    data = strict_json(path, OPERATOR_FIELDS)
    if data["schema_version"] != "1.0.0" or not ID_RE.fullmatch(str(data["operator_id"])) or not ID_RE.fullmatch(str(data["device_id"])):
        raise OpsError("operator_identity")
    fingerprint = str(data["public_key_fingerprint"])
    if not re.fullmatch(r"SHA256:[A-Za-z0-9+/]{20,88}={0,2}", fingerprint):
        raise OpsError("operator_fingerprint")
    return data


def validate_launch_request(path: Path, deployment: dict, operator: dict,
                            dependencies: ProductionDependencies | None = None,
                            *, allow_expired_recovery: bool = False) -> dict:
    dependencies = dependencies or ProductionDependencies()
    data = strict_json(path, LAUNCH_REQUEST_FIELDS)
    try:
        invocation = uuid.UUID(str(data["invocation_id"]))
    except (ValueError, AttributeError) as error:
        raise OpsError("launch_request_identity") from error
    if str(invocation) != data["invocation_id"] or type(data["timestamp_ns"]) is not int or data["timestamp_ns"] <= 0:
        raise OpsError("launch_request_identity")
    if data["schema_version"] != "1.0.0" or data["mode"] != "shadow" or data["confirmation_type"] != "SHAURYA_PREPARE":
        raise OpsError("launch_request_mode")
    if data["operator_id"] != operator["operator_id"] or data["device_id"] != operator["device_id"] or data["deployment_digest"] != deployment["deployment_manifest_digest"]:
        raise OpsError("launch_request_binding", EXIT_REFUSAL)
    if not HEX_RE.fullmatch(str(data["release_digest"])):
        raise OpsError("launch_request_digest")
    if data["public_key_fingerprint"] != operator["public_key_fingerprint"]:
        raise OpsError("launch_request_binding", EXIT_REFUSAL)
    now_ns = dependencies.now_ns()
    if (not allow_expired_recovery and
            (data["timestamp_ns"] > now_ns + 5_000_000_000 or now_ns - data["timestamp_ns"] > 60_000_000_000)):
        raise OpsError("launch_request_expired", EXIT_REFUSAL)
    _, _, release_path = config_paths(dependencies)
    current_release = dependencies.attest_release(release_path)
    if sha256_bytes(canonical(current_release)) != data["release_digest"]:
        raise OpsError("launch_request_release_changed", EXIT_USAGE)
    if os.path.lexists(path.with_name(f"launch-{data['invocation_id']}.consumed.json")):
        raise OpsError("launch_request_consumed", EXIT_REFUSAL)
    return data


def consume_launch_request(path: Path, request: dict, response: dict, dependencies: ProductionDependencies) -> None:
    state_fd, state_identity = open_secure_directory(path.parent, create=False)
    request_fd = None
    try:
        flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
        request_fd = os.open(path.name, flags, dir_fd=state_fd); info = os.fstat(request_fd); raw = os.read(request_fd, 65537)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600
                or raw != canonical(request)): raise OpsError("launch_request_changed", EXIT_REFUSAL)
        tombstone = {"schema_version": "1.0.0", "invocation_id": request["invocation_id"],
                     "attestation_digest": response["attestation_digest"],
                     "execution_session_id": response["execution_session_id"], "consumed_at_ns": dependencies.now_ns()}
        name = f"launch-{request['invocation_id']}.consumed.json"
        create_flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"): create_flags |= os.O_NOFOLLOW
        descriptor = os.open(name, create_flags, 0o600, dir_fd=state_fd)
        with os.fdopen(descriptor, "wb") as output:
            output.write(canonical(tombstone)); output.flush(); os.fsync(output.fileno())
        verify_open_directory(path.parent, state_identity)
        current = os.stat(path.name, dir_fd=state_fd, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino): raise OpsError("launch_request_changed", EXIT_REFUSAL)
        os.unlink(path.name, dir_fd=state_fd); os.fsync(state_fd)
    finally:
        if request_fd is not None: os.close(request_fd)
        os.close(state_fd)


def open_regular_path(path: Path, *, exact_mode: int | None = None) -> tuple[int, int, tuple[int, int]]:
    absolute = Path(os.path.abspath(path)); parent_fd, parent_identity = open_secure_directory(
        absolute.parent, create=False, private_leaf=False)
    try:
        flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
        descriptor = os.open(absolute.name, flags, dir_fd=parent_fd); info = os.fstat(descriptor)
        current = os.stat(absolute.name, dir_fd=parent_fd, follow_symlinks=False)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) & 0o022
                or exact_mode is not None and stat.S_IMODE(info.st_mode) != exact_mode
                or (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino)):
            os.close(descriptor); raise OpsError("unsafe_regular_file", EXIT_REFUSAL)
        return descriptor, parent_fd, parent_identity
    except Exception:
        os.close(parent_fd); raise


def validate_release_data(data: dict) -> dict:
    if data["schema_version"] != "1.0.0" or not ID_RE.fullmatch(str(data["release_version"])) or data["compatibility_version"] != COMPATIBILITY:
        raise OpsError("release_version")
    if not COMMIT_RE.fullmatch(str(data["source_commit"])):
        raise OpsError("release_commit")
    if type(data["source_epoch"]) is not int or data["source_epoch"] < 0 or not HEX_RE.fullmatch(str(data["archive_digest"])):
        raise OpsError("release_metadata")
    files = data["files"]
    if not isinstance(files, list) or not files or len(files) > 512:
        raise OpsError("release_files")
    seen: set[str] = set()
    previous = ""
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "size", "mode", "role"}:
            raise OpsError("release_file_schema")
        name = entry["path"]
        pure = PurePosixPath(str(name))
        if not isinstance(name, str) or name.startswith("/") or pure.as_posix() != name or ".." in pure.parts or name in seen or name <= previous:
            raise OpsError("release_file_path")
        seen.add(name); previous = name
        if not HEX_RE.fullmatch(str(entry["sha256"])) or type(entry["size"]) is not int or entry["size"] < 0 or entry["mode"] not in ("0644", "0755") or not ID_RE.fullmatch(str(entry["role"])):
            raise OpsError("release_file_metadata")
    return data


def validate_release_manifest(path: Path, archive: Path | None = None,
                              archive_descriptor: int | None = None) -> dict:
    data = validate_release_data(strict_json(path, RELEASE_FIELDS, 4 * 1024 * 1024, exact_mode=0o644))
    files = data["files"]
    if archive is not None:
        owned_descriptor = parent_fd = None
        if archive_descriptor is None:
            owned_descriptor, parent_fd, _ = open_regular_path(archive)
            archive_descriptor = owned_descriptor
        if sha256_fd(archive_descriptor) != data["archive_digest"]: raise OpsError("archive_digest_mismatch")
        expected = {entry["path"]: entry for entry in files}
        try:
            os.lseek(archive_descriptor, 0, os.SEEK_SET)
            with os.fdopen(os.dup(archive_descriptor), "rb") as archive_stream, tarfile.open(fileobj=archive_stream, mode="r:gz") as bundle:
                members = bundle.getmembers()
                if len(members) != len(expected) or {member.name for member in members} != set(expected): raise OpsError("archive_manifest_mismatch")
                for member in members:
                    entry = expected[member.name]
                    if (not member.isfile() or member.issym() or member.islnk() or member.name.startswith("/")
                            or ".." in PurePosixPath(member.name).parts or member.size != entry["size"]
                            or stat.S_IMODE(member.mode) != int(entry["mode"], 8) or member.mtime != data["source_epoch"]
                            or member.uid != 0 or member.gid != 0 or member.uname != "" or member.gname != ""
                            or member.pax_headers): raise OpsError("archive_manifest_mismatch")
                    source = bundle.extractfile(member)
                    if source is None or sha256_bytes(source.read()) != entry["sha256"]: raise OpsError("archive_manifest_mismatch")
        except (tarfile.TarError, OSError) as error:
            raise OpsError("archive_malformed") from error
        finally:
            os.lseek(archive_descriptor, 0, os.SEEK_SET)
            if owned_descriptor is not None: os.close(owned_descriptor)
            if parent_fd is not None: os.close(parent_fd)
    return data


def config_paths(dependencies: ProductionDependencies | None = None) -> tuple[Path, Path, Path]:
    dependencies = dependencies or ProductionDependencies()
    home = Path(os.environ.get("HOME", ""))
    config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "kotak"
    state = Path(os.environ.get("XDG_STATE_HOME", home / ".local/state")) / "kotak"
    release = dependencies.release_manifest_path(Path(__file__).resolve().parents[1] / "release-manifest.json")
    return config, state, release


def deployment_path() -> Path:
    config, _, _ = config_paths()
    return config / "deployment.json"


def operator_path() -> Path:
    config, _, _ = config_paths()
    return config / "operator-device.json"


def validate_system_command(path: Path) -> None:
    try: info = os.stat(path, follow_symlinks=False)
    except OSError as error: raise OpsError("local_dependency_unavailable", EXIT_USAGE) from error
    if (not path.is_absolute() or path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) & 0o022 or not os.access(path, os.X_OK)):
        raise OpsError("local_dependency_unsafe", EXIT_USAGE)


def validate_local_capabilities(dependencies: ProductionDependencies) -> None:
    if dependencies.local_platform() != "darwin": raise OpsError("unsupported_local_platform", EXIT_USAGE)
    if dependencies.local_architecture() not in {"arm64", "x86_64"}:
        raise OpsError("unsupported_local_architecture", EXIT_USAGE)
    if sys.version_info < (3, 9): raise OpsError("unsupported_python", EXIT_USAGE)
    for raw in dependencies.required_local_commands(): validate_system_command(Path(raw))


def public_key_fingerprint(public_line: bytes) -> str:
    try:
        text = public_line.decode("ascii", "strict").strip(); fields = text.split()
        if len(fields) not in (2, 3) or fields[0] not in {"ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256"}:
            raise ValueError
        blob = base64.b64decode(fields[1], validate=True)
    except (UnicodeError, ValueError) as error:
        raise OpsError("ssh_identity_public_key_invalid", EXIT_USAGE) from error
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii").rstrip("=")


def open_transport_file(path: Path, *, exact_mode: int) -> tuple[int, int, tuple[int, int], os.stat_result]:
    try: descriptor, parent_fd, parent_identity = open_regular_path(path, exact_mode=exact_mode)
    except OSError as error: raise OpsError("transport_file_unsafe", EXIT_USAGE) from error
    info = os.fstat(descriptor)
    return descriptor, parent_fd, parent_identity, info


def transport_file_digest(descriptor: int, *, maximum: int = 64 * 1024) -> str:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode) or before.st_size < 1 or before.st_size > maximum:
        raise OpsError("transport_file_unsafe", EXIT_USAGE)
    digest = hashlib.sha256(); total = 0; buffer = bytearray(4096)
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        while True:
            count = os.readv(descriptor, [buffer])
            if count == 0: break
            total += count
            if total > maximum: raise OpsError("transport_file_unsafe", EXIT_USAGE)
            digest.update(memoryview(buffer)[:count])
        after = os.fstat(descriptor)
        if total != before.st_size or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise OpsError("transport_file_changed", EXIT_USAGE)
        return digest.hexdigest()
    finally:
        wipe_bytearray(buffer)
        try: os.lseek(descriptor, 0, os.SEEK_SET)
        except OSError: pass


def immutable_transport_snapshot(source_fd: int, expected_digest: str, root: Path,
                                 label: str) -> int:
    if label not in {"identity", "known-hosts"}: raise OpsError("transport_snapshot_label", EXIT_INTERNAL)
    root_fd, root_identity = open_secure_directory(root, create=False, private_leaf=False)
    directory_name = f".kotak-transport-{uuid.uuid4().hex}"
    directory_fd = writer_fd = snapshot_fd = None
    created_directory = created_file = False
    try:
        os.mkdir(directory_name, 0o700, dir_fd=root_fd); created_directory = True
        directory_fd, _ = open_directory_at(root_fd, directory_name, create=False, mode=0o700)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
        writer_fd = os.open(label, flags, 0o600, dir_fd=directory_fd); created_file = True
        digest = hashlib.sha256(); total = 0; buffer = bytearray(4096)
        try:
            os.lseek(source_fd, 0, os.SEEK_SET)
            while True:
                count = os.readv(source_fd, [buffer])
                if count == 0: break
                total += count
                if total > 64 * 1024: raise OpsError("transport_file_unsafe", EXIT_USAGE)
                view = memoryview(buffer)[:count]; digest.update(view)
                written = 0
                while written < count:
                    written += os.write(writer_fd, view[written:])
        finally:
            wipe_bytearray(buffer); os.lseek(source_fd, 0, os.SEEK_SET)
        if total == 0 or digest.hexdigest() != expected_digest:
            raise OpsError("transport_file_changed", EXIT_USAGE)
        os.close(writer_fd); writer_fd = None
        read_flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"): read_flags |= os.O_NOFOLLOW
        snapshot_fd = os.open(label, read_flags, dir_fd=directory_fd)
        snapshot_info = os.fstat(snapshot_fd)
        if (not stat.S_ISREG(snapshot_info.st_mode) or snapshot_info.st_uid != os.geteuid()
                or stat.S_IMODE(snapshot_info.st_mode) != 0o600
                or transport_file_digest(snapshot_fd) != expected_digest):
            raise OpsError("transport_snapshot_invalid", EXIT_INTERNAL)
        os.unlink(label, dir_fd=directory_fd); created_file = False; os.fsync(directory_fd)
        os.rmdir(directory_name, dir_fd=root_fd); created_directory = False; os.fsync(root_fd)
        verify_open_directory(root, root_identity)
        result = snapshot_fd; snapshot_fd = None
        return result
    finally:
        for descriptor in (writer_fd, snapshot_fd):
            if descriptor is not None:
                try: os.close(descriptor)
                except OSError: pass
        if directory_fd is not None:
            if created_file:
                try: os.unlink(label, dir_fd=directory_fd)
                except OSError: pass
            try: os.close(directory_fd)
            except OSError: pass
        if created_directory:
            try: os.rmdir(directory_name, dir_fd=root_fd); os.fsync(root_fd)
            except OSError: pass
        os.close(root_fd)


def revalidate_transport_file(path: Path, parent_fd: int, parent_identity: tuple[int, int],
                              info: os.stat_result, descriptor: int, expected_digest: str) -> None:
    try:
        verify_open_directory(path.parent, parent_identity)
        current = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as error: raise OpsError("transport_file_changed", EXIT_USAGE) from error
    if (not stat.S_ISREG(current.st_mode) or current.st_uid != os.geteuid()
            or stat.S_IMODE(current.st_mode) != 0o600
            or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)
            or transport_file_digest(descriptor) != expected_digest):
        raise OpsError("transport_file_changed", EXIT_USAGE)


def validate_known_hosts(descriptor: int, host_alias: str) -> None:
    raw = bytearray(); os.lseek(descriptor, 0, os.SEEK_SET)
    while block := os.read(descriptor, 4096):
        raw.extend(block)
        if len(raw) > 64 * 1024: raise OpsError("known_hosts_invalid", EXIT_USAGE)
    os.lseek(descriptor, 0, os.SEEK_SET)
    try:
        lines = raw.decode("ascii", "strict").splitlines()
        matches = [line.split() for line in lines if line and not line.startswith("#")]
        if not any(len(fields) >= 3 and host_alias in fields[0].split(",")
                   and fields[1] in {"ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256"}
                   and base64.b64decode(fields[2], validate=True) for fields in matches):
            raise ValueError
    except (UnicodeError, ValueError) as error:
        raise OpsError("known_hosts_invalid", EXIT_USAGE) from error
    finally:
        wipe_bytearray(raw)


def run_remote(command: str, deployment: dict, payload: bytearray | None = None,
               dependencies: ProductionDependencies | None = None) -> tuple[int, dict | None]:
    dependencies = dependencies or ProductionDependencies(); ssh = dependencies.ssh_path
    if not os.path.isabs(ssh): raise OpsError("ssh_path_not_absolute", EXIT_INTERNAL)
    try:
        ssh_stat = os.stat(ssh, follow_symlinks=False)
        if not stat.S_ISREG(ssh_stat.st_mode) or stat.S_IMODE(ssh_stat.st_mode) & 0o022:
            raise OpsError("ssh_binary_unsafe", EXIT_INTERNAL)
        if ssh == "/usr/bin/ssh" and ssh_stat.st_uid != 0: raise OpsError("ssh_binary_unsafe", EXIT_INTERNAL)
    except OSError as error:
        raise OpsError("ssh_binary_unavailable", EXIT_UNAVAILABLE) from error
    timeout = deployment["timeouts"]; identity = dependencies.ssh_identity_path(); known_hosts = dependencies.ssh_known_hosts_path()
    identity_fd = identity_parent_fd = known_hosts_fd = known_hosts_parent_fd = None
    identity_snapshot_fd = known_hosts_snapshot_fd = None
    try:
        identity_fd, identity_parent_fd, identity_parent_identity, identity_info = open_transport_file(identity, exact_mode=0o600)
        known_hosts_fd, known_hosts_parent_fd, known_hosts_parent_identity, known_hosts_info = open_transport_file(known_hosts, exact_mode=0o600)
        identity_digest = transport_file_digest(identity_fd)
        known_hosts_digest = transport_file_digest(known_hosts_fd)
        snapshot_root = dependencies.transport_snapshot_root()
        identity_snapshot_fd = immutable_transport_snapshot(identity_fd, identity_digest, snapshot_root, "identity")
        known_hosts_snapshot_fd = immutable_transport_snapshot(known_hosts_fd, known_hosts_digest, snapshot_root, "known-hosts")
        validate_known_hosts(known_hosts_snapshot_fd, deployment["ssh_host_alias"])
        operator = validate_operator(operator_path())
        if public_key_fingerprint(dependencies.identity_public_key(identity_snapshot_fd)) != operator["public_key_fingerprint"]:
            raise OpsError("ssh_identity_fingerprint_mismatch", EXIT_USAGE)
        revalidate_transport_file(identity, identity_parent_fd, identity_parent_identity, identity_info,
                                  identity_fd, identity_digest)
        revalidate_transport_file(known_hosts, known_hosts_parent_fd, known_hosts_parent_identity,
                                  known_hosts_info, known_hosts_fd, known_hosts_digest)
        dependencies.adversarial_swap(identity, "identity_before_popen")
        dependencies.adversarial_swap(known_hosts, "known_hosts_before_popen")
        revalidate_transport_file(identity, identity_parent_fd, identity_parent_identity, identity_info,
                                  identity_fd, identity_digest)
        revalidate_transport_file(known_hosts, known_hosts_parent_fd, known_hosts_parent_identity,
                                  known_hosts_info, known_hosts_fd, known_hosts_digest)
        if (transport_file_digest(identity_snapshot_fd) != identity_digest
                or transport_file_digest(known_hosts_snapshot_fd) != known_hosts_digest):
            raise OpsError("transport_snapshot_changed", EXIT_INTERNAL)
        # The server-side key is restricted to a root-controlled forced
        # command. Send a closed protocol token, never a manifest pathname.
        helper = "shaurya-operator-v1"
        argv = [ssh, "-F", "/dev/null", "-T", "-oBatchMode=yes", "-oPasswordAuthentication=no",
                "-oKbdInteractiveAuthentication=no", "-oForwardAgent=no", "-oClearAllForwardings=yes",
                "-oStrictHostKeyChecking=yes", "-oConnectionAttempts=1", "-oPermitLocalCommand=no",
                "-oProxyCommand=none", "-oProxyJump=none", "-oRequestTTY=no", "-oIdentitiesOnly=yes",
                "-oIdentityAgent=none", "-i", f"/dev/fd/{identity_snapshot_fd}", "-oPubkeyAuthentication=yes",
                "-oPreferredAuthentications=publickey", "-oNumberOfPasswordPrompts=0", "-oCanonicalizeHostname=no",
                f"-oUserKnownHostsFile=/dev/fd/{known_hosts_snapshot_fd}", "-oGlobalKnownHostsFile=/dev/null",
                "-oUpdateHostKeys=no", f"-oConnectTimeout={timeout['connect_seconds']}",
                f"-oServerAliveInterval={timeout['server_alive_seconds']}", "-oServerAliveCountMax=1",
                deployment["ssh_host_alias"], helper, command]
        process = dependencies.popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     env=dependencies.child_environment(), bufsize=0,
                                     pass_fds=(identity_snapshot_fd, known_hosts_snapshot_fd))
        if process.stdin is None or process.stdout is None: process.kill(); process.wait(); return EXIT_INTERNAL, None
        outgoing = memoryview(payload if payload is not None else bytearray())
        os.set_blocking(process.stdout.fileno(), False); os.set_blocking(process.stdin.fileno(), False)
        selector = selectors.DefaultSelector(); selector.register(process.stdout, selectors.EVENT_READ)
        if outgoing: selector.register(process.stdin, selectors.EVENT_WRITE)
        else: process.stdin.close()
        captured = bytearray(); deadline = time.monotonic() + timeout["operation_seconds"]
        timed_out = overflow = False
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0: timed_out = True; break
            for key, _ in selector.select(remaining):
                if key.fileobj is process.stdout:
                    block = os.read(process.stdout.fileno(), 4096)
                    if not block: selector.unregister(process.stdout); process.stdout.close()
                    else:
                        captured.extend(block)
                        if len(captured) > 16 * 1024: overflow = True; break
                else:
                    try: count = os.write(process.stdin.fileno(), outgoing[:4096])
                    except BrokenPipeError: count = len(outgoing)
                    outgoing = outgoing[count:]
                    if not outgoing: selector.unregister(process.stdin); process.stdin.close()
            if overflow: break
        selector.close()
        if timed_out or overflow:
            process.kill(); process.wait()
            return (EXIT_TIMEOUT if timed_out else EXIT_INTERNAL), None
        try: returncode = process.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired: process.kill(); process.wait(); return EXIT_TIMEOUT, None
        if returncode != 0: return EXIT_REFUSAL if returncode == 3 else EXIT_UNAVAILABLE, None
        stdout = bytes(captured)
        try: response = json.loads(stdout.decode("ascii"), object_pairs_hook=_unique_object)
        except (UnicodeError, json.JSONDecodeError, OpsError): return EXIT_UNAVAILABLE, None
        if (not isinstance(response, dict) or not all(isinstance(key, str) for key in response)
                or canonical(response) != stdout): return EXIT_UNAVAILABLE, None
        return EXIT_SUCCESS, response
    except OSError as error:
        raise OpsError("transport_trust_file_unavailable", EXIT_USAGE) from error
    finally:
        for descriptor in (identity_fd, identity_parent_fd, known_hosts_fd, known_hosts_parent_fd,
                           identity_snapshot_fd, known_hosts_snapshot_fd):
            if descriptor is not None:
                try: os.close(descriptor)
                except OSError: pass


def validate_remote_response(command: str, response: dict, deployment: dict, request: dict | None = None) -> bool:
    if command in ("doctor", "preflight", "status"):
        allowed = {"status", "remote_os", "remote_architecture", "executor_commit", "executor_source_state",
                   "executor_source_tree_sha256", "executor_build_digest",
                   "deployment_digest", "live_gate", "unit_status", "timer_present", "protocol_versions",
                   "auth_helper_digest", "doctor_helper_digest", "broker_helper_digest", "protocol_helper_digest", "watcher_digest",
                   "orchestration_unit", "unit_template_digest", "execution_session_id"}
        if (set(response) != allowed or response["status"] != "ok"
                or response["executor_source_state"] != "clean" or response["live_gate"] != "OFF"
                or response["unit_status"] != "inactive" or response["timer_present"] is not False):
            return False
        return response["remote_os"] == deployment["expected_remote_os"] and response["remote_architecture"] == deployment["expected_remote_architecture"] and response["executor_commit"] == deployment["executor_commit"] and response["executor_source_tree_sha256"] == deployment["executor_source_tree_sha256"] and response["executor_build_digest"] == deployment["executor_build_digest"] and response["deployment_digest"] == deployment["deployment_manifest_digest"] and response["protocol_versions"] == deployment["protocol_versions"] and response["auth_helper_digest"] == deployment["auth_helper_digest"] and response["doctor_helper_digest"] == deployment["doctor_helper_digest"] and response["broker_helper_digest"] == deployment["broker_helper_digest"] and response["protocol_helper_digest"] == deployment["protocol_helper_digest"] and response["watcher_digest"] == deployment["watcher_digest"] and response["orchestration_unit"] == deployment["orchestration_unit"] and response["unit_template_digest"] == deployment["unit_template_digest"] and canonical_uuid(str(response["execution_session_id"]))
    if command == "auth":
        return (set(response) == {"status", "diagnostic_ok"}
                and response["status"] == "synthetic_transport_only" and response["diagnostic_ok"] is True)
    if command == "launch":
        required = {"status", "invocation_id", "unit_instance", "attestation_digest", "execution_session_id",
                    "executor_build_digest", "restart", "persistent_timer", "ready", "peers_ready",
                    "observation_fresh", "attested", "ledger_ready", "claim_consumed", "live_gate",
                    "timer_present", "cleanup_complete"}
        return (request is not None and set(response) == required and response["status"] == "ok"
                and response["invocation_id"] == request["invocation_id"]
                and response["unit_instance"] == f"shaurya-shadow-once@{request['invocation_id']}.service"
                and HEX_RE.fullmatch(str(response["attestation_digest"])) is not None
                and canonical_uuid(str(response["execution_session_id"]))
                and response["executor_build_digest"] == deployment["executor_build_digest"]
                and response["restart"] == "no" and response["persistent_timer"] is False
                and all(response[key] is True for key in {"ready", "peers_ready", "observation_fresh", "attested", "ledger_ready", "claim_consumed", "cleanup_complete"})
                and response["live_gate"] == "OFF" and response["timer_present"] is False)
    return False


def hidden_code(terminal: TerminalDependencies | None = None) -> bytearray:
    terminal = terminal or TerminalDependencies(); descriptor = None; echo_state = None; value = bytearray(); failure = None
    try:
        descriptor = terminal.open(); echo_state = terminal.disable_echo(descriptor); terminal.write_prompt(descriptor)
        while len(value) <= 6:
            item = terminal.read_byte(descriptor)
            if not item or item in (b"\n", b"\r"): break
            value.extend(item)
    except BaseException as error:
        failure = error
    finally:
        if descriptor is not None:
            try:
                if echo_state is not None: terminal.restore_echo(descriptor, echo_state)
                terminal.write_newline(descriptor)
            except BaseException as error:
                if failure is None: failure = error
            finally:
                try: terminal.close(descriptor)
                except BaseException as error:
                    if failure is None: failure = error
    if failure is not None:
        wipe_bytearray(value)
        if isinstance(failure, OpsError): raise failure
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise OpsError("auth_interrupted", EXIT_UNAVAILABLE) from failure
        raise OpsError("auth_terminal_unavailable", EXIT_UNAVAILABLE) from failure
    if len(value) != 6 or any(item < 48 or item > 57 for item in value):
        wipe_bytearray(value); raise OpsError("auth_code_invalid", EXIT_USAGE)
    return value


def validate_no_duplicates(argv: list[str]) -> None:
    for flag in ("--dry-run", "--remote", "--confirm"):
        if argv.count(flag) > 1:
            raise OpsError("duplicate_flag")


def validate_offline_doctor(dependencies: ProductionDependencies) -> dict:
    config, state, release = config_paths(dependencies)
    if not release.exists() or not deployment_path().exists() or not operator_path().exists():
        raise OpsError("installation_incomplete", EXIT_REFUSAL)
    validate_local_capabilities(dependencies)
    installed_release = dependencies.attest_release(release)
    if (installed_release["release_version"] != dependencies.release_version()
            or COMMIT_RE.fullmatch(str(installed_release["source_commit"])) is None):
        raise OpsError("installed_release_identity", EXIT_USAGE)
    local_deployment = validate_deployment(deployment_path())
    local_operator = validate_operator(operator_path())
    identity = dependencies.ssh_identity_path(); known_hosts = dependencies.ssh_known_hosts_path()
    identity_fd = identity_parent_fd = known_hosts_fd = known_hosts_parent_fd = None
    try:
        identity_fd, identity_parent_fd, identity_parent_identity, identity_info = open_transport_file(identity, exact_mode=0o600)
        known_hosts_fd, known_hosts_parent_fd, known_hosts_parent_identity, known_hosts_info = open_transport_file(known_hosts, exact_mode=0o600)
        validate_known_hosts(known_hosts_fd, local_deployment["ssh_host_alias"])
        if public_key_fingerprint(dependencies.identity_public_key(identity_fd)) != local_operator["public_key_fingerprint"]:
            raise OpsError("ssh_identity_fingerprint_mismatch", EXIT_USAGE)
        revalidate_transport_file(identity, identity_parent_fd, identity_parent_identity, identity_info,
                                  identity_fd, transport_file_digest(identity_fd))
        revalidate_transport_file(known_hosts, known_hosts_parent_fd, known_hosts_parent_identity,
                                  known_hosts_info, known_hosts_fd, transport_file_digest(known_hosts_fd))
    finally:
        for descriptor in (identity_fd, identity_parent_fd, known_hosts_fd, known_hosts_parent_fd):
            if descriptor is not None:
                try: os.close(descriptor)
                except OSError: pass
    for directory in (config, state):
        if directory.exists():
            descriptor, _ = open_secure_directory(directory, create=False)
            os.close(descriptor)
    return local_deployment


def cli(argv: list[str], dependencies: ProductionDependencies | None = None) -> int:
    dependencies = dependencies or ProductionDependencies()
    if not argv or argv == ["help"] or argv == ["--help"]:
        print("kotak 1.0.0\ncommands: help version doctor auth status prepare preflight shaurya-shadow-launch shadow-launch")
        return EXIT_SUCCESS
    validate_no_duplicates(argv)
    command = argv[0]
    if command == "version" and len(argv) == 1:
        print(f"kotak {VERSION} compatibility={COMPATIBILITY}")
        return EXIT_SUCCESS
    known = {"doctor", "auth", "status", "prepare", "preflight", "shaurya-shadow-launch", "shadow-launch"}
    if command not in known:
        return emit("parser", "usage_refused", EXIT_USAGE)
    dry = "--dry-run" in argv
    remote = "--remote" in argv
    confirmation = None
    cleaned: list[str] = []
    index = 1
    while index < len(argv):
        token = argv[index]
        if token in ("--dry-run", "--remote"):
            index += 1; continue
        if token == "--confirm" and index + 1 < len(argv):
            confirmation = argv[index + 1]; index += 2; continue
        cleaned.append(token); index += 1
    if cleaned or (remote and command != "doctor"):
        return emit(command, "usage_refused", EXIT_USAGE)
    canonical_command = "shaurya-shadow-launch" if command == "shadow-launch" else command
    required_confirmation = {"auth": "KOTAK_AUTH", "prepare": "SHAURYA_PREPARE", "shaurya-shadow-launch": "SHAURYA_SHADOW_LAUNCH"}.get(canonical_command)
    if confirmation is not None and required_confirmation is None:
        return emit(canonical_command, "usage_refused", EXIT_USAGE)
    if required_confirmation is not None and confirmation != required_confirmation:
        return emit(canonical_command, "confirmation_refused", EXIT_USAGE)
    if dry:
        return emit(canonical_command, "dry_run", EXIT_SUCCESS, "yes")
    try:
        deployment = validate_deployment(deployment_path()) if remote or canonical_command not in ("doctor",) else None
        if canonical_command == "doctor" and not remote:
            validate_offline_doctor(dependencies)
            return emit("doctor", "success", EXIT_SUCCESS, "yes")
        if canonical_command == "doctor" and remote:
            deployment = validate_offline_doctor(dependencies)
            code, response = run_remote("doctor", deployment, dependencies=dependencies)
            if code != 0: return emit_audited("doctor", "timeout" if code == EXIT_TIMEOUT else "remote_refused", code)
            valid = validate_remote_response("doctor", response or {}, deployment)
            return emit_audited("doctor", "success" if valid else "unverified",
                                EXIT_SUCCESS if valid else EXIT_UNAVAILABLE,
                                "yes" if valid else "no")
        if canonical_command == "auth":
            # Establish the pinned-host, fixed forced-command trust boundary and
            # measure the installed helper set before any diagnostic bytes exist.
            preflight_code, preflight_response = run_remote("doctor", deployment, dependencies=dependencies)
            if preflight_code != 0:
                return emit_audited("auth", "timeout" if preflight_code == EXIT_TIMEOUT else "refused", preflight_code)
            if not validate_remote_response("doctor", preflight_response or {}, deployment):
                return emit_audited("auth", "unverified", EXIT_UNAVAILABLE, "no")
            code_value = hidden_code()
            try:
                code_value.append(10)
                code, response = run_remote("auth", deployment, code_value, dependencies)
            finally:
                wipe_bytearray(code_value)
            if code != 0: return emit_audited("auth", "timeout" if code == EXIT_TIMEOUT else "refused", code)
            valid = validate_remote_response("auth", response or {}, deployment)
            return emit_audited("auth", "diagnostic" if valid else "unverified", EXIT_SUCCESS if valid else EXIT_UNAVAILABLE, "no")
        if canonical_command == "prepare":
            operator = validate_operator(operator_path())
            _, state, release_path = config_paths(dependencies)
            release = dependencies.attest_release(release_path)
            request = {"schema_version": "1.0.0", "invocation_id": dependencies.new_invocation_id(),
                       "timestamp_ns": dependencies.now_ns(),
                       "operator_id": operator["operator_id"], "device_id": operator["device_id"],
                       "public_key_fingerprint": operator["public_key_fingerprint"],
                       "release_digest": sha256_bytes(canonical(release)), "deployment_digest": deployment["deployment_manifest_digest"],
                       "mode": "shadow", "confirmation_type": "SHAURYA_PREPARE"}
            state_fd, state_identity = open_secure_directory(state, create=True)
            destination = "launch-request.json"
            temporary = f".launch-request.{os.getpid()}"
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_CLOEXEC
            if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
            descriptor = os.open(temporary, flags, 0o600, dir_fd=state_fd)
            try:
                with os.fdopen(descriptor, "wb") as stream: stream.write(canonical(request)); stream.flush(); os.fsync(stream.fileno())
                dependencies.adversarial_swap(state, "state_before_publish")
                verify_open_directory(state, state_identity)
                os.link(temporary, destination, src_dir_fd=state_fd, dst_dir_fd=state_fd, follow_symlinks=False)
                os.unlink(temporary, dir_fd=state_fd); os.fsync(state_fd)
            except Exception:
                try: os.unlink(temporary, dir_fd=state_fd)
                except OSError: pass
                raise
            finally:
                os.close(state_fd)
            return emit_audited("prepare", "success", EXIT_SUCCESS, "yes")
        if canonical_command in ("status", "preflight", "shaurya-shadow-launch"):
            request_payload = None
            if canonical_command in ("preflight", "shaurya-shadow-launch"):
                _, state, _ = config_paths()
                request = validate_launch_request(state / "launch-request.json", deployment,
                                                  validate_operator(operator_path()), dependencies,
                                                  allow_expired_recovery=canonical_command == "shaurya-shadow-launch")
                request_payload = canonical(request)
            remote_command = "launch" if canonical_command == "shaurya-shadow-launch" else canonical_command
            mutable_payload = bytearray(request_payload) if request_payload is not None else None
            try: code, response = run_remote(remote_command, deployment, mutable_payload, dependencies)
            finally:
                if mutable_payload is not None: wipe_bytearray(mutable_payload)
            if code != 0: return emit_audited(canonical_command, "timeout" if code == EXIT_TIMEOUT else "remote_refused", code)
            valid = validate_remote_response(remote_command if remote_command != "preflight" else "preflight", response or {}, deployment, request if remote_command == "launch" else None)
            if valid and remote_command == "launch":
                consume_launch_request(state / "launch-request.json", request, response or {}, dependencies)
            return emit_audited(canonical_command, "success" if valid else "unverified", EXIT_SUCCESS if valid else EXIT_UNAVAILABLE, "yes" if valid else "no")
    except OpsError as error:
        code = EXIT_USAGE if error.exit_code == EXIT_REFUSAL else error.exit_code
        return emit(canonical_command, error.code, code)
    except Exception:
        return emit(canonical_command, "internal_failure", EXIT_INTERNAL)
    return emit(canonical_command, "internal_failure", EXIT_INTERNAL)


def _read_packaged_source(root_fd: int, relative: str) -> bytes:
    pure = PurePosixPath(relative)
    parent_fd = open_nested_directory(root_fd, pure.parts[:-1], create=False)
    try:
        flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
        descriptor = os.open(pure.parts[-1], flags, dir_fd=parent_fd)
        try:
            before = os.fstat(descriptor); data = bytearray()
            while block := os.read(descriptor, 1024 * 1024):
                data.extend(block)
                if len(data) > 16 * 1024 * 1024: raise OpsError("package_source_unsafe", EXIT_REFUSAL)
            current = os.stat(pure.parts[-1], dir_fd=parent_fd, follow_symlinks=False)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                    or stat.S_IMODE(before.st_mode) & 0o022
                    or (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino)
                    or before.st_size != len(data)):
                raise OpsError("package_source_unsafe", EXIT_REFUSAL)
            return bytes(data)
        finally: os.close(descriptor)
    finally: os.close(parent_fd)


def source_files(root_fd: int, source_revision: str) -> list[tuple[bytes, str, int, str]]:
    names = ["kotak", "install.sh", "uninstall.sh", "package_release.sh", "verify_manifest.sh", "README.md"]
    libexec_names = ["kotak-auth-helper", "kotak-remote-doctor", "portable_ops.py", "remote_protocol.py",
                     "select-python", "shaurya-session-broker", "shaurya-shadow-watcher"]
    manifest_names = ["deployment.example.json", "operator-device.example.json"]
    if COMMIT_RE.fullmatch(source_revision) is None: raise OpsError("source_revision_unverified", EXIT_REFUSAL)
    output: list[tuple[bytes, str, int, str]] = [(f"{source_revision}\n".encode("ascii"), "SOURCE_REVISION", 0o644, "provenance")]
    for name in names:
        output.append((_read_packaged_source(root_fd, name), name,
                       0o755 if name.endswith(".sh") or name == "kotak" else 0o644,
                       "command" if name != "README.md" else "documentation"))
    for name in libexec_names:
        output.append((_read_packaged_source(root_fd, f"libexec/{name}"), f"libexec/{name}",
                       0o644 if name.endswith(".py") else 0o755, "libexec"))
    for name in manifest_names:
        output.append((_read_packaged_source(root_fd, f"manifests/{name}"), f"manifests/{name}", 0o644, "example"))
    return sorted(output, key=lambda item: item[1])


def package_release(args: list[str], expected_version: str = VERSION,
                    verified_source_revision: str | None = None) -> int:
    parser = ClosedParser()
    parser.add_argument("--output-dir", required=True); parser.add_argument("--version", required=True)
    parser.add_argument("--source-epoch", required=True, type=int); parser.add_argument("--source-commit", required=True)
    for flag in ("--output-dir", "--version", "--source-epoch", "--source-commit"):
        if args.count(flag) > 1: raise OpsError("duplicate_argument")
    options = parser.parse_args(args)
    if (options.version != expected_version or options.source_epoch < 0
            or not COMMIT_RE.fullmatch(options.source_commit)
            or verified_source_revision is None or options.source_commit != verified_source_revision):
        raise OpsError("package_metadata")
    root = Path(__file__).resolve().parents[1]; root_fd, _ = open_secure_directory(root, create=False, private_leaf=False)
    destination = Path(options.output_dir)
    if not destination.is_absolute(): raise OpsError("package_output_unsafe")
    destination_fd, _ = open_secure_directory(destination, create=True, private_leaf=False)
    try: files = source_files(root_fd, verified_source_revision)
    finally: os.close(root_fd)
    archive_name = f"kotak-{options.version}.tar.gz"; archive = destination / archive_name
    archive_flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"): archive_flags |= os.O_NOFOLLOW
    archive_fd = os.open(archive_name, archive_flags, 0o644, dir_fd=destination_fd)
    with os.fdopen(archive_fd, "wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=options.source_epoch) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as bundle:
                for data, name, mode, _ in files:
                    info = tarfile.TarInfo(name); info.size = len(data); info.mode = mode
                    info.mtime = options.source_epoch; info.uid = info.gid = 0; info.uname = info.gname = ""; info.pax_headers = {}
                    bundle.addfile(info, io.BytesIO(data))
    entries = [{"path": name, "sha256": sha256_bytes(data), "size": len(data),
                "mode": format(mode, "04o"), "role": role} for data, name, mode, role in files]
    read_flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"): read_flags |= os.O_NOFOLLOW
    archive_read_fd = os.open(archive_name, read_flags, dir_fd=destination_fd); archive_digest = sha256_fd(archive_read_fd); os.close(archive_read_fd)
    manifest = {"schema_version": "1.0.0", "release_version": options.version, "compatibility_version": COMPATIBILITY,
                "source_commit": options.source_commit, "source_epoch": options.source_epoch,
                "archive_digest": archive_digest, "files": entries}
    manifest_name = f"kotak-{options.version}.manifest.json"; manifest_path = destination / manifest_name
    manifest_flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"): manifest_flags |= os.O_NOFOLLOW
    descriptor = os.open(manifest_name, manifest_flags, 0o644, dir_fd=destination_fd)
    with os.fdopen(descriptor, "wb") as output:
        output.write(canonical(manifest)); output.flush(); os.fsync(output.fileno())
    os.fsync(destination_fd); os.close(destination_fd)
    print(f"archive={archive}\nmanifest={manifest_path}")
    return 0


def safe_prefix(raw: str) -> Path:
    if not raw or not os.path.isabs(raw): raise OpsError("prefix_not_absolute")
    lexical = PurePosixPath(raw)
    if any(part in (".", "..") for part in lexical.parts): raise OpsError("prefix_not_normalized")
    normalized = os.path.normpath(raw)
    if normalized != raw.rstrip("/") or "//" in raw: raise OpsError("prefix_not_normalized")
    path = Path(normalized)
    configured_home = Path(os.path.normpath(os.environ.get("HOME", "/nonexistent")))
    real_home = Path(pwd.getpwuid(os.geteuid()).pw_dir)
    system_roots = tuple(Path(item) for item in ("/usr", "/opt", "/etc", "/var", "/System", "/Library",
                                                   "/Applications", "/bin", "/sbin", "/private/var"))
    home_ancestor = any(home.is_absolute() and (path == home or home.is_relative_to(path))
                        for home in (configured_home, real_home))
    if (len(path.parts) < 4 or path in (Path("/"), Path("/Users"), Path("/private"), Path("/private/tmp"))
            or home_ancestor or any(path == root or path.is_relative_to(root) for root in system_roots)):
        raise OpsError("prefix_too_broad")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.exists() and current.is_symlink(): raise OpsError("prefix_symlink")
    return path


def default_prefix() -> str:
    home = os.environ.get("HOME", "")
    if not home or not os.path.isabs(home): raise OpsError("home_unavailable", EXIT_USAGE)
    return str(Path(home) / ".local")


class OperationLock:
    def __init__(self, state_fd: int, lock_fd: int, identity: tuple[int, int], owner: bytes):
        self.state_fd, self.lock_fd, self.identity, self.owner = state_fd, lock_fd, identity, owner


def acquire_lock(prefix_fd: int) -> OperationLock:
    state_fd = os.dup(prefix_fd); lock_fd = None
    try:
        flags = os.O_CREAT | os.O_RDWR | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
        lock_fd = os.open(".kotak-release-operation.lock", flags, 0o600, dir_fd=state_fd); info = os.fstat(lock_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise OpsError("operation_lock_unsafe", EXIT_USAGE)
        try: fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error: raise OpsError("operation_locked", EXIT_USAGE) from error
        owner = canonical({"pid": os.getpid(), "schema_version": "1.0.0", "token": str(uuid.uuid4())})
        os.ftruncate(lock_fd, 0); os.lseek(lock_fd, 0, os.SEEK_SET); os.write(lock_fd, owner); os.fsync(lock_fd); os.fsync(state_fd)
        return OperationLock(state_fd, lock_fd, (info.st_dev, info.st_ino), owner)
    except Exception:
        if lock_fd is not None: os.close(lock_fd)
        os.close(state_fd); raise


def release_lock(lock: OperationLock) -> None:
    try:
        current = os.stat(".kotak-release-operation.lock", dir_fd=lock.state_fd, follow_symlinks=False)
        if (not stat.S_ISREG(current.st_mode) or (current.st_dev, current.st_ino) != lock.identity): return
        os.lseek(lock.lock_fd, 0, os.SEEK_SET)
        if os.read(lock.lock_fd, len(lock.owner) + 1) != lock.owner: return
    except OSError: return
    finally:
        try: fcntl.flock(lock.lock_fd, fcntl.LOCK_UN)
        except OSError: pass
        os.close(lock.lock_fd); os.close(lock.state_fd)


def load_release_index_at(parent_fd: int, name: str = "release-index.json") -> dict[str, str]:
    if not exists_at(parent_fd, name): return {}
    try:
        flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
        descriptor = os.open(name, flags, dir_fd=parent_fd)
        try: info = os.fstat(descriptor); raw = os.read(descriptor, 64 * 1024 + 1)
        finally: os.close(descriptor)
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or not 0 < len(raw) <= 64 * 1024
                or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)):
            raise OpsError("release_index_malformed", EXIT_REFUSAL)
        value = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError, OpsError) as error: raise OpsError("release_index_malformed", EXIT_REFUSAL) from error
    if not isinstance(value, dict) or len(value) > 64 or any(not ID_RE.fullmatch(str(version)) or not HEX_RE.fullmatch(str(digest)) for version, digest in value.items()):
        raise OpsError("release_index_malformed", EXIT_REFUSAL)
    if canonical(dict(sorted(value.items()))) != raw: raise OpsError("release_index_malformed", EXIT_REFUSAL)
    return value


TRANSACTION_FIELDS = {"schema_version", "old_current", "old_previous", "old_index", "old_installed", "new_current",
                      "new_release_created", "new_stage", "launcher_created_this_transaction"}
INSTALLED_FIELDS = {"schema_version", "current_version", "current_target", "previous_target", "launcher_sha256",
                    "launcher_created", "owned_releases", "release_manifest_digest", "release_index_digest"}
UNINSTALL_TRANSACTION_FIELDS = {"schema_version", "phase", "stage", "installed"}
LAUNCHER_BYTES = (b'#!/bin/sh\nset -eu\ncase "$0" in */*) parent=${0%/*} ;; *) parent=. ;; esac\n'
                  b'prefix=$(CDPATH= cd -- "$parent/.." && pwd -P)\nbase=$prefix/libexec/kotak\n'
                  b'case "${1-}" in --internal-*) printf "%s\\n" "[KOTAK_RESULT] command=parser status=usage_refused code=2 verified=no"; exit 2 ;; esac\n'
                  b'if [ -e "$base/transaction.json" ]; then [ -L "$base/transaction-current" ] || exit 70; exec "$base/transaction-current/kotak" "$@"; fi\n'
                  b'[ ! -e "$base/uninstall-transaction.json" ] || exit 70\n[ -L "$base/current" ] || exit 70\n'
                  b'exec "$base/current/kotak" "$@"\n')


def recover_transaction(base_fd: int, prefix_fd: int) -> None:
    if not exists_at(base_fd, "transaction.json"): return
    value, journal_identity = strict_json_at(base_fd, "transaction.json", TRANSACTION_FIELDS, exact_mode=0o600)
    def transaction_target(target: object, *, allow_none: bool) -> bool:
        if allow_none and target == "none": return True
        if not isinstance(target, str): return False
        pure = PurePosixPath(target)
        return len(pure.parts) == 2 and pure.parts[0] == "releases" and ID_RE.fullmatch(pure.parts[1]) is not None
    old_index = value["old_index"]
    if (value["schema_version"] != "1.0.0" or not transaction_target(value["old_current"], allow_none=True)
            or not transaction_target(value["old_previous"], allow_none=True)
            or not transaction_target(value["new_current"], allow_none=False)
            or not isinstance(value["new_stage"], str)
            or value["new_stage"] != "none" and re.fullmatch(r"releases/\.staging-[A-Za-z0-9._-]{1,64}-[1-9][0-9]{0,9}", value["new_stage"]) is None
            or not isinstance(old_index, dict) or len(old_index) > 64
            or any(not isinstance(version, str) or ID_RE.fullmatch(version) is None
                   or not isinstance(digest, str) or HEX_RE.fullmatch(digest) is None for version, digest in old_index.items())
            or value["old_installed"] is not None and (not isinstance(value["old_installed"], dict)
                                                        or set(value["old_installed"]) != INSTALLED_FIELDS)):
        raise OpsError("transaction_malformed", EXIT_REFUSAL)
    if type(value["new_release_created"]) is not bool or type(value["launcher_created_this_transaction"]) is not bool:
        raise OpsError("transaction_malformed", EXIT_REFUSAL)
    if value["old_current"] == "none":
        if exists_at(base_fd, "transaction-current"): raise OpsError("transaction_fallback_malformed", EXIT_USAGE)
    elif (not exists_at(base_fd, "transaction-current")
          or validated_pointer_at(base_fd, "transaction-current", old_index) != value["old_current"]):
        raise OpsError("transaction_fallback_malformed", EXIT_USAGE)
    atomic_symlink_at(base_fd, "current", None if value["old_current"] == "none" else value["old_current"])
    atomic_symlink_at(base_fd, "previous", None if value["old_previous"] == "none" else value["old_previous"])
    if value["old_index"]: atomic_private_json_at(base_fd, "release-index.json", dict(sorted(value["old_index"].items())))
    elif exists_at(base_fd, "release-index.json"): unlink_exact_regular_at(base_fd, "release-index.json")
    if value["old_installed"] is not None: atomic_private_json_at(base_fd, "installed-manifest.json", value["old_installed"])
    elif exists_at(base_fd, "installed-manifest.json"): unlink_exact_regular_at(base_fd, "installed-manifest.json")
    if value["launcher_created_this_transaction"]:
        expected = LAUNCHER_BYTES
        bin_fd, _ = open_directory_at(prefix_fd, "bin", create=False)
        try:
            if not exists_at(bin_fd, "kotak"): pass
            else:
                flags = os.O_RDONLY | os.O_CLOEXEC
                if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
                descriptor = os.open("kotak", flags, dir_fd=bin_fd)
                try: info = os.fstat(descriptor); actual = os.read(descriptor, len(expected) + 1)
                finally: os.close(descriptor)
                if not stat.S_ISREG(info.st_mode) or actual != expected: raise OpsError("transaction_launcher_changed", EXIT_REFUSAL)
                unlink_exact_regular_at(bin_fd, "kotak", (info.st_dev, info.st_ino))
        finally: os.close(bin_fd)
    releases_fd, releases_identity = open_directory_at(base_fd, "releases", create=False)
    try:
        if value["new_release_created"]:
            version = PurePosixPath(value["new_current"]).parts[1]
            if exists_at(releases_fd, version):
                manifest = validate_release_manifest_at(releases_fd, version)
                if not release_dir_valid_at(releases_fd, version, manifest): raise OpsError("transaction_release_changed", EXIT_REFUSAL)
                remove_release_tree_at(releases_fd, version, manifest)
        if value["new_stage"] != "none":
            stage = PurePosixPath(value["new_stage"]).parts[1]
            if exists_at(releases_fd, stage):
                manifest = validate_release_manifest_at(releases_fd, stage)
                if not release_dir_valid_at(releases_fd, stage, manifest): raise OpsError("transaction_stage_changed", EXIT_REFUSAL)
                remove_release_tree_at(releases_fd, stage, manifest)
    finally: os.close(releases_fd)
    unlink_exact_regular_at(base_fd, "transaction.json", journal_identity)
    if value["old_current"] != "none": unlink_exact_symlink_at(base_fd, "transaction-current", value["old_current"])


def remove_release_tree_at(parent_fd: int, release_name: str, manifest: dict, *, allow_missing: bool = False,
                           dependencies: ProductionDependencies | None = None) -> None:
    release_fd, release_identity = open_directory_at(parent_fd, release_name, create=False)
    try:
        for entry in reversed(manifest["files"]):
            pure = PurePosixPath(entry["path"])
            try: file_parent_fd = open_nested_directory(release_fd, pure.parts[:-1], create=False)
            except FileNotFoundError:
                if allow_missing: continue
                raise
            try:
                flags = os.O_RDONLY | os.O_CLOEXEC
                if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
                try: descriptor = os.open(pure.parts[-1], flags, dir_fd=file_parent_fd)
                except FileNotFoundError:
                    if allow_missing: continue
                    raise
                try:
                    info = os.fstat(descriptor)
                    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                            or sha256_fd(descriptor) != entry["sha256"] or info.st_size != entry["size"]
                            or stat.S_IMODE(info.st_mode) != int(entry["mode"], 8)):
                        raise OpsError("release_changed_during_removal", EXIT_REFUSAL)
                    current = os.stat(pure.parts[-1], dir_fd=file_parent_fd, follow_symlinks=False)
                    if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                        raise OpsError("release_changed_during_removal", EXIT_REFUSAL)
                    os.unlink(pure.parts[-1], dir_fd=file_parent_fd); os.fsync(file_parent_fd)
                finally: os.close(descriptor)
            finally: os.close(file_parent_fd)
        directories = {PurePosixPath(entry["path"]).parent for entry in manifest["files"]
                       if PurePosixPath(entry["path"]).parent != PurePosixPath(".")}
        for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
            try: ancestor_fd = open_nested_directory(release_fd, directory.parts[:-1], create=False)
            except FileNotFoundError:
                if allow_missing: continue
                raise
            try:
                try: os.rmdir(directory.parts[-1], dir_fd=ancestor_fd); os.fsync(ancestor_fd)
                except FileNotFoundError:
                    if not allow_missing: raise
            finally: os.close(ancestor_fd)
        if dependencies is not None: dependencies.interruption("uninstall_before_manifest_remove")
        flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
        try: descriptor = os.open("release-manifest.json", flags, dir_fd=release_fd)
        except FileNotFoundError:
            if not allow_missing or observed_tree(release_fd): raise OpsError("release_changed_during_removal", EXIT_REFUSAL)
            descriptor = None
        try:
            if descriptor is not None:
                info = os.fstat(descriptor)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                        or sha256_fd(descriptor) != sha256_bytes(canonical(manifest))):
                    raise OpsError("release_changed_during_removal", EXIT_REFUSAL)
                current = os.stat("release-manifest.json", dir_fd=release_fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                    raise OpsError("release_changed_during_removal", EXIT_REFUSAL)
                os.unlink("release-manifest.json", dir_fd=release_fd); os.fsync(release_fd)
        finally:
            if descriptor is not None: os.close(descriptor)
        if dependencies is not None: dependencies.interruption("uninstall_after_manifest")
        current_release = os.stat(release_name, dir_fd=parent_fd, follow_symlinks=False)
        if (current_release.st_dev, current_release.st_ino) != release_identity:
            raise OpsError("release_changed_during_removal", EXIT_REFUSAL)
    finally: os.close(release_fd)
    os.rmdir(release_name, dir_fd=parent_fd); os.fsync(parent_fd)


def release_dir_valid_at(releases_fd: int, version: str, manifest: dict) -> bool:
    try: release_fd, _ = open_directory_at(releases_fd, version, create=False)
    except (OSError, OpsError): return False
    try:
        for entry in manifest["files"]:
            info, digest = regular_digest_at(release_fd, entry["path"])
            if digest != entry["sha256"] or info.st_size != entry["size"] or stat.S_IMODE(info.st_mode) != int(entry["mode"], 8): return False
        info, digest = regular_digest_at(release_fd, "release-manifest.json")
        if stat.S_IMODE(info.st_mode) != 0o644 or digest != sha256_bytes(canonical(manifest)): return False
        return observed_tree(release_fd) == {entry["path"] for entry in manifest["files"]} | {"release-manifest.json"}
    except (OSError, OpsError): return False
    finally: os.close(release_fd)


def validate_release_manifest_at(releases_fd: int, version: str) -> dict:
    if ID_RE.fullmatch(version) is None: raise OpsError("release_version", EXIT_REFUSAL)
    release_fd, _ = open_directory_at(releases_fd, version, create=False)
    try:
        value, _ = strict_json_at(release_fd, "release-manifest.json", RELEASE_FIELDS,
                                  4 * 1024 * 1024, exact_mode=0o644)
        return validate_release_data(value)
    finally: os.close(release_fd)


def extract_release_at(releases_fd: int, stage_name: str, archive_descriptor: int, manifest: dict) -> None:
    os.mkdir(stage_name, 0o700, dir_fd=releases_fd); stage_fd, _ = open_directory_at(releases_fd, stage_name)
    try:
        os.lseek(archive_descriptor, 0, os.SEEK_SET)
        with os.fdopen(os.dup(archive_descriptor), "rb") as archive_stream, tarfile.open(fileobj=archive_stream, mode="r:gz") as bundle:
            members = bundle.getmembers(); expected = {entry["path"] for entry in manifest["files"]}
            if {item.name for item in members} != expected: raise OpsError("archive_unsafe")
            by_name = {entry["path"]: entry for entry in manifest["files"]}
            for member in members:
                if (not member.isfile() or member.issym() or member.islnk() or member.name.startswith("/")
                        or ".." in PurePosixPath(member.name).parts): raise OpsError("archive_unsafe")
                entry = by_name[member.name]; pure = PurePosixPath(member.name)
                parent_fd = open_nested_directory(stage_fd, pure.parts[:-1], create=True)
                try:
                    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_CLOEXEC
                    if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
                    descriptor = os.open(pure.parts[-1], flags, int(entry["mode"], 8), dir_fd=parent_fd)
                    source = bundle.extractfile(member)
                    if source is None: os.close(descriptor); raise OpsError("archive_unsafe")
                    with os.fdopen(descriptor, "wb") as output:
                        shutil.copyfileobj(source, output); output.flush(); os.fsync(output.fileno())
                finally: os.close(parent_fd)
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
        descriptor = os.open("release-manifest.json", flags, 0o644, dir_fd=stage_fd)
        with os.fdopen(descriptor, "wb") as output:
            output.write(canonical(manifest)); output.flush(); os.fsync(output.fileno())
        os.fsync(stage_fd)
    finally: os.close(stage_fd)
    if not release_dir_valid_at(releases_fd, stage_name, manifest): raise OpsError("installed_verification_failed")


def validated_pointer_at(base_fd: int, pointer_name: str, release_index: dict[str, str]) -> str | None:
    if not exists_at(base_fd, pointer_name): return None
    info = os.stat(pointer_name, dir_fd=base_fd, follow_symlinks=False)
    if not stat.S_ISLNK(info.st_mode): raise OpsError("foreign_release_pointer", EXIT_REFUSAL)
    target = os.readlink(pointer_name, dir_fd=base_fd)
    pure = PurePosixPath(target)
    if len(pure.parts) != 2 or pure.parts[0] != "releases" or not ID_RE.fullmatch(pure.parts[1]):
        raise OpsError("foreign_release_pointer", EXIT_REFUSAL)
    releases_fd, releases_identity = open_directory_at(base_fd, "releases", create=False)
    try: manifest = validate_release_manifest_at(releases_fd, pure.parts[1])
    except OpsError as error: raise OpsError("foreign_release_pointer", EXIT_REFUSAL) from error
    finally:
        if 'manifest' not in locals(): os.close(releases_fd)
    if release_index.get(pure.parts[1]) != sha256_bytes(canonical(manifest)) or not release_dir_valid_at(releases_fd, pure.parts[1], manifest):
        os.close(releases_fd)
        raise OpsError("foreign_release_pointer", EXIT_REFUSAL)
    os.close(releases_fd)
    return target


def attest_installed_release(release_manifest_path: Path) -> dict:
    release = release_manifest_path.parent; base = release_manifest_path.parents[2]
    prefix = base.parents[1]
    if (base.name != "kotak" or release.parent.name != "releases" or release_manifest_path.name != "release-manifest.json"
            or not prefix.is_absolute()):
        raise OpsError("installed_release_layout", EXIT_REFUSAL)
    prefix_fd, _ = open_secure_directory(prefix, create=False, private_leaf=False)
    base_fd = releases_fd = bin_fd = None
    try:
        base_fd = open_nested_directory(prefix_fd, ("libexec", "kotak"), create=False)
        if exists_at(base_fd, "transaction.json") or exists_at(base_fd, "uninstall-transaction.json"):
            raise OpsError("installed_release_transaction", EXIT_REFUSAL)
        releases_fd, _ = open_directory_at(base_fd, "releases", create=False)
        manifest = validate_release_manifest_at(releases_fd, release.name)
        if release.name != manifest["release_version"]: raise OpsError("installed_release_layout", EXIT_REFUSAL)
        release_index = load_release_index_at(base_fd)
        target = validated_pointer_at(base_fd, "current", release_index)
        expected_target = f"releases/{manifest['release_version']}"
        installed = strict_json_at(base_fd, "installed-manifest.json", INSTALLED_FIELDS, exact_mode=0o600)[0]
        digest = sha256_bytes(canonical(manifest)); _, index_digest = regular_digest_at(base_fd, "release-index.json")
        observed_releases = {entry.name for entry in os.scandir(releases_fd)}
        if observed_releases != set(release_index): raise OpsError("installed_release_mismatch", EXIT_REFUSAL)
        for version, recorded in release_index.items():
            candidate = validate_release_manifest_at(releases_fd, version)
            if recorded != sha256_bytes(canonical(candidate)) or not release_dir_valid_at(releases_fd, version, candidate):
                raise OpsError("installed_release_mismatch", EXIT_REFUSAL)
        bin_fd, _ = open_directory_at(prefix_fd, "bin", create=False); launcher_info, launcher_digest = regular_digest_at(bin_fd, "kotak")
        provenance = [entry for entry in manifest["files"] if entry["path"] == "SOURCE_REVISION"]
        expected_revision = f"{manifest['source_commit']}\n".encode("ascii")
        if (len(provenance) != 1 or provenance[0]["role"] != "provenance"
                or provenance[0]["mode"] != "0644" or provenance[0]["size"] != len(expected_revision)
                or provenance[0]["sha256"] != sha256_bytes(expected_revision)):
            raise OpsError("installed_source_revision", EXIT_REFUSAL)
        if (stat.S_IMODE(launcher_info.st_mode) != 0o755 or target != expected_target
                or release_index.get(manifest["release_version"]) != digest
                or installed["current_version"] != manifest["release_version"] or installed["current_target"] != expected_target
                or installed["release_manifest_digest"] != digest or installed["release_index_digest"] != index_digest
                or sorted(release_index) != installed["owned_releases"] or launcher_digest != installed["launcher_sha256"]):
            raise OpsError("installed_release_mismatch", EXIT_REFUSAL)
        return manifest
    finally:
        if bin_fd is not None: os.close(bin_fd)
        if releases_fd is not None: os.close(releases_fd)
        if base_fd is not None: os.close(base_fd)
        os.close(prefix_fd)


def install_release(args: list[str], dependencies: ProductionDependencies | None = None) -> int:
    dependencies = dependencies or ProductionDependencies()
    parser = ClosedParser(); parser.add_argument("--prefix", default=None); parser.add_argument("--archive"); parser.add_argument("--manifest"); parser.add_argument("--rollback")
    for flag in ("--prefix", "--archive", "--manifest", "--rollback"):
        if args.count(flag) > 1: raise OpsError("duplicate_argument")
    options = parser.parse_args(args); prefix = safe_prefix(options.prefix or default_prefix()); prefix_fd, prefix_identity = open_secure_directory(prefix, create=True, private_leaf=False)
    try: lock = acquire_lock(prefix_fd)
    except Exception: os.close(prefix_fd); raise
    base_fd = releases_fd = bin_fd = None
    try:
        dependencies.adversarial_swap(prefix / ".kotak-release-operation.lock", "lock_after_acquire")
        dependencies.adversarial_swap(prefix, "prefix_after_open")
        verify_open_directory(prefix, prefix_identity)
        base = prefix / "libexec/kotak"; releases = base / "releases"; index_path = base / "release-index.json"
        base_fd = open_nested_directory(prefix_fd, ("libexec", "kotak"), create=True)
        if not exists_at(base_fd, "releases") and any(exists_at(base_fd, name) for name in
                                                       ("current", "previous", "release-index.json", "installed-manifest.json")):
            raise OpsError("foreign_release_state", EXIT_REFUSAL)
        releases_fd, _ = open_directory_at(base_fd, "releases", create=True)
        if exists_at(base_fd, "uninstall-transaction.json"):
            pending = strict_json_at(base_fd, "uninstall-transaction.json", UNINSTALL_TRANSACTION_FIELDS, exact_mode=0o600)[0]
            run_uninstall_transaction(prefix_fd, pending["installed"], dependencies)
        recover_transaction(base_fd, prefix_fd)
        release_index = load_release_index_at(base_fd); original_index = dict(release_index)
        current = base / "current"; previous = base / "previous"
        old = validated_pointer_at(base_fd, "current", release_index)
        old_previous = validated_pointer_at(base_fd, "previous", release_index) if exists_at(base_fd, "previous") else None
        if exists_at(base_fd, "transaction-current"):
            orphan = validated_pointer_at(base_fd, "transaction-current", release_index)
            if orphan != old: raise OpsError("transaction_fallback_malformed", EXIT_USAGE)
            unlink_exact_symlink_at(base_fd, "transaction-current", old)
        installed_path = base / "installed-manifest.json"
        old_installed = strict_json_at(base_fd, "installed-manifest.json", INSTALLED_FIELDS, exact_mode=0o600)[0] if exists_at(base_fd, "installed-manifest.json") else None
        bin_dir = prefix / "bin"; bin_fd, _ = open_directory_at(prefix_fd, "bin", create=True); launcher = bin_dir / "kotak"
        launcher_bytes = LAUNCHER_BYTES
        try:
            launcher_info = os.stat("kotak", dir_fd=bin_fd, follow_symlinks=False); launcher_existed = True
            flags = os.O_RDONLY | os.O_CLOEXEC
            if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
            descriptor = os.open("kotak", flags, dir_fd=bin_fd)
            with os.fdopen(descriptor, "rb") as stream: launcher_actual = stream.read(len(launcher_bytes) + 1)
            if (not stat.S_ISREG(launcher_info.st_mode) or launcher_info.st_uid != os.geteuid()
                    or launcher_actual != launcher_bytes or stat.S_IMODE(launcher_info.st_mode) != 0o755): raise OpsError("foreign_launcher", EXIT_REFUSAL)
        except FileNotFoundError: launcher_existed = False
        launcher_created = bool(old_installed["launcher_created"]) if old_installed is not None else not launcher_existed
        if options.rollback and (options.archive or options.manifest): raise OpsError("install_arguments")
        new_release_created = False; stage = None; archive_fd = archive_parent_fd = None
        if options.rollback:
            manifest_path = releases / options.rollback / "release-manifest.json"; manifest = validate_release_manifest(manifest_path)
            target = releases / options.rollback
            manifest_digest = sha256_bytes(canonical(manifest))
            if release_index.get(options.rollback) != manifest_digest or not release_dir_valid_at(releases_fd, options.rollback, manifest): raise OpsError("rollback_digest_mismatch")
        else:
            if not options.archive or not options.manifest: raise OpsError("install_arguments")
            archive = Path(options.archive); manifest_path = Path(options.manifest)
            archive_fd, archive_parent_fd, _ = open_regular_path(archive)
            manifest = validate_release_manifest(manifest_path, archive, archive_fd)
            version = manifest["release_version"]; target = releases / version
            manifest_digest = sha256_bytes(canonical(manifest))
            if version not in release_index and len(release_index) >= 64: raise OpsError("release_index_full", EXIT_REFUSAL)
            if version in release_index and release_index[version] != manifest_digest: raise OpsError("release_index_conflict", EXIT_REFUSAL)
            try: target_info = os.stat(version, dir_fd=releases_fd, follow_symlinks=False); target_exists = True
            except FileNotFoundError: target_exists = False
            if target_exists:
                if not stat.S_ISDIR(target_info.st_mode): raise OpsError("unowned_existing_release", EXIT_REFUSAL)
                if version not in release_index: raise OpsError("unowned_existing_release", EXIT_REFUSAL)
                if not release_dir_valid_at(releases_fd, version, manifest): raise OpsError("existing_release_differs", EXIT_REFUSAL)
            else:
                stage_name = f".staging-{version}-{os.getpid()}"; stage = releases / stage_name
                extract_release_at(releases_fd, stage_name, archive_fd, manifest)
                try: dependencies.interruption("after_stage")
                except Exception:
                    if release_dir_valid_at(releases_fd, stage_name, manifest): remove_release_tree_at(releases_fd, stage_name, manifest)
                    raise
                new_release_created = True
            release_index[version] = manifest_digest
        transaction = {"schema_version": "1.0.0", "old_current": old or "none", "old_previous": old_previous or "none",
                       "old_index": original_index, "old_installed": old_installed,
                       "new_current": str(target.relative_to(base)), "new_release_created": new_release_created,
                       "new_stage": str(stage.relative_to(base)) if stage is not None else "none",
                       "launcher_created_this_transaction": not launcher_existed}
        if old: atomic_symlink_at(base_fd, "transaction-current", old)
        atomic_private_json_at(base_fd, "transaction.json", transaction)
        dependencies.interruption("before_release_publish")
        if stage is not None:
            verify_open_directory(prefix, prefix_identity); os.replace(stage.name, target.name, src_dir_fd=releases_fd, dst_dir_fd=releases_fd); os.fsync(releases_fd)
        dependencies.interruption("after_release_publish")
        if not launcher_existed:
            launcher_tmp = f".kotak-{os.getpid()}"
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_CLOEXEC
            if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
            descriptor = os.open(launcher_tmp, flags, 0o755, dir_fd=bin_fd)
            with os.fdopen(descriptor, "wb") as output: output.write(launcher_bytes); output.flush(); os.fsync(output.fileno())
            os.replace(launcher_tmp, "kotak", src_dir_fd=bin_fd, dst_dir_fd=bin_fd); os.fsync(bin_fd)
        verify_open_directory(prefix, prefix_identity)
        atomic_symlink_at(base_fd, "current", str(target.relative_to(base)))
        dependencies.interruption("after_current")
        if old:
            atomic_symlink_at(base_fd, "previous", old)
        elif exists_at(base_fd, "previous"): atomic_symlink_at(base_fd, "previous", None)
        dependencies.interruption("after_previous")
        atomic_private_json_at(base_fd, "release-index.json", dict(sorted(release_index.items())))
        dependencies.interruption("after_index")
        owned = sorted(release_index)
        installed = {"schema_version": "1.0.0", "current_version": target.name, "current_target": os.readlink("current", dir_fd=base_fd),
                     "previous_target": os.readlink("previous", dir_fd=base_fd) if exists_at(base_fd, "previous") else "none",
                     "launcher_sha256": sha256_bytes(launcher_bytes), "launcher_created": launcher_created,
                     "owned_releases": owned, "release_manifest_digest": sha256_bytes(canonical(manifest)),
                     "release_index_digest": regular_digest_at(base_fd, "release-index.json")[1]}
        atomic_private_json_at(base_fd, "installed-manifest.json", installed); dependencies.interruption("after_installed")
        _, journal_identity = strict_json_at(base_fd, "transaction.json", TRANSACTION_FIELDS, exact_mode=0o600)
        unlink_exact_regular_at(base_fd, "transaction.json", journal_identity)
        if old: unlink_exact_symlink_at(base_fd, "transaction-current", old)
        print(marker("install", "success", 0, "yes")); return 0
    finally:
        if 'archive_fd' in locals() and archive_fd is not None: os.close(archive_fd)
        if 'archive_parent_fd' in locals() and archive_parent_fd is not None: os.close(archive_parent_fd)
        if bin_fd is not None: os.close(bin_fd)
        if releases_fd is not None: os.close(releases_fd)
        if base_fd is not None: os.close(base_fd)
        if prefix_fd is not None: os.close(prefix_fd)
        release_lock(lock)


def exists_at(descriptor: int, name: str) -> bool:
    try: os.stat(name, dir_fd=descriptor, follow_symlinks=False); return True
    except FileNotFoundError: return False


def move_once(source_fd: int, source: str, destination_fd: int, destination: str) -> None:
    source_exists = exists_at(source_fd, source); destination_exists = exists_at(destination_fd, destination)
    if source_exists and destination_exists: raise OpsError("uninstall_stage_conflict", EXIT_REFUSAL)
    if source_exists:
        os.replace(source, destination, src_dir_fd=source_fd, dst_dir_fd=destination_fd)
        os.fsync(source_fd)
        if destination_fd != source_fd: os.fsync(destination_fd)
    elif not destination_exists: raise OpsError("uninstall_stage_missing", EXIT_REFUSAL)


def remove_empty_directory_at(parent_fd: int, name: str) -> bool:
    try: descriptor, identity = open_directory_at(parent_fd, name, create=False)
    except FileNotFoundError: return True
    try:
        if any(True for _ in os.scandir(descriptor)): return False
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != identity: raise OpsError("directory_identity_changed", EXIT_REFUSAL)
    finally: os.close(descriptor)
    os.rmdir(name, dir_fd=parent_fd); os.fsync(parent_fd); return True


def cleanup_empty_install_directories(prefix_fd: int) -> None:
    try: libexec_fd, _ = open_directory_at(prefix_fd, "libexec", create=False)
    except FileNotFoundError: libexec_fd = None
    if libexec_fd is not None:
        try: remove_empty_directory_at(libexec_fd, "kotak")
        finally: os.close(libexec_fd)
        remove_empty_directory_at(prefix_fd, "libexec")
    remove_empty_directory_at(prefix_fd, "bin")


def run_uninstall_transaction(prefix_fd: int, expected: dict, dependencies: ProductionDependencies) -> None:
    base_fd = open_nested_directory(prefix_fd, ("libexec", "kotak"), create=False)
    releases_fd = bin_fd = -1; releases_identity = None
    try:
        if exists_at(base_fd, "uninstall-transaction.json"):
            transaction = strict_json_at(base_fd, "uninstall-transaction.json", UNINSTALL_TRANSACTION_FIELDS, exact_mode=0o600)[0]
            if transaction["installed"] != expected: raise OpsError("uninstall_transaction_mismatch", EXIT_REFUSAL)
        else:
            stage_name = f".uninstall-stage-{uuid.uuid4()}"
            transaction = {"schema_version": "1.0.0", "phase": "staging", "stage": stage_name, "installed": expected}
            atomic_private_json_at(base_fd, "uninstall-transaction.json", transaction)
        if (transaction["schema_version"] != "1.0.0" or transaction["phase"] not in {"staging", "commit"}
                or re.fullmatch(r"\.uninstall-stage-[0-9a-f-]{36}", str(transaction["stage"])) is None):
            raise OpsError("uninstall_transaction_malformed", EXIT_REFUSAL)
        try: releases_fd, releases_identity = open_directory_at(base_fd, "releases", create=False)
        except FileNotFoundError:
            if transaction["phase"] != "commit": raise OpsError("uninstall_stage_missing", EXIT_REFUSAL)
        bin_fd, _ = open_directory_at(prefix_fd, "bin", create=False)
        stage_name = transaction["stage"]
        stage_fd, _ = open_directory_at(base_fd, stage_name, create=True)
        stage_releases_fd, _ = open_directory_at(stage_fd, "releases", create=True)
        try:
            if transaction["phase"] == "staging":
                for name in ("current", "release-index.json", "installed-manifest.json"):
                    move_once(base_fd, name, stage_fd, name)
                if expected["previous_target"] != "none": move_once(base_fd, "previous", stage_fd, "previous")
                elif exists_at(base_fd, "previous"): raise OpsError("uninstall_pointer_mismatch", EXIT_REFUSAL)
                if releases_fd < 0: raise OpsError("uninstall_stage_missing", EXIT_REFUSAL)
                for version in expected["owned_releases"]: move_once(releases_fd, version, stage_releases_fd, version)
                dependencies.interruption("uninstall_after_stage")
                transaction = dict(transaction); transaction["phase"] = "commit"; atomic_private_json_at(base_fd, "uninstall-transaction.json", transaction)
            dependencies.interruption("uninstall_after_commit")
            for version in expected["owned_releases"]:
                if exists_at(stage_releases_fd, version):
                    try: manifest = validate_release_manifest_at(stage_releases_fd, version)
                    except OpsError:
                        release_fd, release_identity = open_directory_at(stage_releases_fd, version, create=False)
                        try:
                            if observed_tree(release_fd): raise OpsError("uninstall_release_modified", EXIT_REFUSAL)
                            current = os.stat(version, dir_fd=stage_releases_fd, follow_symlinks=False)
                            if (current.st_dev, current.st_ino) != release_identity: raise OpsError("directory_identity_changed", EXIT_REFUSAL)
                        finally: os.close(release_fd)
                        os.rmdir(version, dir_fd=stage_releases_fd); os.fsync(stage_releases_fd)
                    else: remove_release_tree_at(stage_releases_fd, version, manifest, allow_missing=True, dependencies=dependencies)
                    dependencies.interruption("uninstall_after_release")
            if expected["launcher_created"] and (exists_at(bin_fd, "kotak") or exists_at(stage_fd, "launcher")):
                move_once(bin_fd, "kotak", stage_fd, "launcher")
            dependencies.interruption("uninstall_after_launcher_stage")
            for name in ("current", "previous", "release-index.json", "installed-manifest.json", "launcher"):
                if exists_at(stage_fd, name): os.unlink(name, dir_fd=stage_fd); os.fsync(stage_fd)
            dependencies.interruption("uninstall_after_metadata")
            os.rmdir("releases", dir_fd=stage_fd); os.fsync(stage_fd); os.close(stage_releases_fd); stage_releases_fd = -1
            os.rmdir(stage_name, dir_fd=base_fd); os.fsync(base_fd)
            dependencies.interruption("uninstall_after_stage_directory")
            if releases_fd >= 0:
                current_releases = os.stat("releases", dir_fd=base_fd, follow_symlinks=False)
                if (current_releases.st_dev, current_releases.st_ino) != releases_identity:
                    raise OpsError("directory_identity_changed", EXIT_REFUSAL)
                os.close(releases_fd); releases_fd = -1
                os.rmdir("releases", dir_fd=base_fd); os.fsync(base_fd)
            dependencies.interruption("uninstall_after_releases_directory")
            _, journal_identity = strict_json_at(base_fd, "uninstall-transaction.json", UNINSTALL_TRANSACTION_FIELDS, exact_mode=0o600)
            unlink_exact_regular_at(base_fd, "uninstall-transaction.json", journal_identity)
            dependencies.interruption("uninstall_after_journal")
        finally:
            if stage_releases_fd >= 0: os.close(stage_releases_fd)
            os.close(stage_fd)
    finally:
        if bin_fd >= 0: os.close(bin_fd)
        if releases_fd >= 0: os.close(releases_fd)
        os.close(base_fd)


def uninstall_release(args: list[str], dependencies: ProductionDependencies | None = None) -> int:
    dependencies = dependencies or ProductionDependencies()
    parser = ClosedParser(); parser.add_argument("--prefix", default=None); parser.add_argument("--installed-manifest", required=True)
    for flag in ("--prefix", "--installed-manifest"):
        if args.count(flag) > 1: raise OpsError("duplicate_argument")
    options = parser.parse_args(args); prefix = safe_prefix(options.prefix or default_prefix()); prefix_fd, prefix_identity = open_secure_directory(prefix, create=False, private_leaf=False)
    try: lock = acquire_lock(prefix_fd)
    except Exception: os.close(prefix_fd); raise
    try:
        dependencies.adversarial_swap(prefix, "prefix_after_open")
        verify_open_directory(prefix, prefix_identity)
        return uninstall_release_locked(prefix, prefix_fd, Path(options.installed_manifest), prefix_identity, dependencies)
    finally:
        if prefix_fd is not None: os.close(prefix_fd)
        release_lock(lock)


def uninstall_release_locked(prefix: Path, prefix_fd: int, supplied_manifest: Path, prefix_identity: tuple[int, int], dependencies: ProductionDependencies) -> int:
    base = prefix / "libexec/kotak"
    expected = strict_json(supplied_manifest, INSTALLED_FIELDS)
    base_fd = open_nested_directory(prefix_fd, ("libexec", "kotak"), create=False)
    if exists_at(base_fd, "uninstall-transaction.json"):
        os.close(base_fd)
        run_uninstall_transaction(prefix_fd, expected, dependencies)
        cleanup_empty_install_directories(prefix_fd)
        print(marker("uninstall", "success", 0, "yes")); return 0
    bin_fd = releases_fd = None
    try:
        if not exists_at(base_fd, "installed-manifest.json") and not exists_at(base_fd, "uninstall-transaction.json"):
            bin_check_fd = None
            try:
                bin_check_fd, _ = open_directory_at(prefix_fd, "bin", create=False)
                launcher_present = exists_at(bin_check_fd, "kotak")
                if launcher_present:
                    _, launcher_digest = regular_digest_at(bin_check_fd, "kotak")
                if ((launcher_present and (expected["launcher_created"] or launcher_digest != expected["launcher_sha256"]))
                        or observed_tree(base_fd)):
                    raise OpsError("uninstall_state_missing", EXIT_REFUSAL)
            finally:
                if bin_check_fd is not None: os.close(bin_check_fd)
            os.close(base_fd); base_fd = None
            cleanup_empty_install_directories(prefix_fd)
            print(marker("uninstall", "success", 0, "yes")); return 0
        actual = strict_json_at(base_fd, "installed-manifest.json", INSTALLED_FIELDS, exact_mode=0o600)[0]
        if actual != expected: raise OpsError("installed_manifest_mismatch", EXIT_REFUSAL)
        if (expected["schema_version"] != "1.0.0" or type(expected["launcher_created"]) is not bool
                or not isinstance(expected["owned_releases"], list) or not expected["owned_releases"]
                or expected["owned_releases"] != sorted(set(expected["owned_releases"]))
                or any(not isinstance(item, str) or not ID_RE.fullmatch(item) for item in expected["owned_releases"])
                or not HEX_RE.fullmatch(str(expected["launcher_sha256"]))
                or not HEX_RE.fullmatch(str(expected["release_index_digest"]))):
            raise OpsError("installed_manifest_malformed", EXIT_REFUSAL)
        bin_fd, _ = open_directory_at(prefix_fd, "bin", create=False)
        _, launcher_digest = regular_digest_at(bin_fd, "kotak")
        if launcher_digest != expected["launcher_sha256"]: raise OpsError("uninstall_modified_launcher", EXIT_REFUSAL)
        release_index = load_release_index_at(base_fd)
        current_target = validated_pointer_at(base_fd, "current", release_index)
        previous_target = validated_pointer_at(base_fd, "previous", release_index) if exists_at(base_fd, "previous") else None
        if current_target != expected["current_target"] or (previous_target or "none") != expected["previous_target"]:
            raise OpsError("uninstall_pointer_mismatch", EXIT_REFUSAL)
        _, index_digest = regular_digest_at(base_fd, "release-index.json")
        if (index_digest != expected["release_index_digest"] or sorted(release_index) != expected["owned_releases"]
                or release_index.get(expected["current_version"]) != expected["release_manifest_digest"]):
            raise OpsError("uninstall_release_modified", EXIT_REFUSAL)
        releases_fd, _ = open_directory_at(base_fd, "releases", create=False)
        for version in expected["owned_releases"]:
            manifest = validate_release_manifest_at(releases_fd, version)
            if sha256_bytes(canonical(manifest)) != release_index[version] or not release_dir_valid_at(releases_fd, version, manifest):
                raise OpsError("uninstall_release_modified", EXIT_REFUSAL)
    finally:
        if releases_fd is not None: os.close(releases_fd)
        if bin_fd is not None: os.close(bin_fd)
        if base_fd is not None: os.close(base_fd)
    verify_open_directory(prefix, prefix_identity)
    run_uninstall_transaction(prefix_fd, expected, dependencies)
    cleanup_empty_install_directories(prefix_fd)
    print(marker("uninstall", "success", 0, "yes")); return 0


def main(dependencies: ProductionDependencies | None = None) -> int:
    dependencies = dependencies or ProductionDependencies()
    arguments = sys.argv[1:]; internal = arguments[0] if arguments and arguments[0].startswith("--internal-") else None
    if internal is not None: arguments = arguments[1:]
    mode = {"--internal-package": "package", "--internal-verify": "verify", "--internal-install": "install",
            "--internal-uninstall": "uninstall"}.get(internal, "cli")
    try:
        if mode == "package":
            source_root = Path(__file__).resolve().parents[1]
            return package_release(arguments, dependencies.release_version(), dependencies.source_revision(source_root))
        if mode == "verify":
            if len(arguments) not in (1, 2): raise OpsError("verify_arguments")
            validate_release_manifest(Path(arguments[0]), Path(arguments[1]) if len(arguments) == 2 else None); print(marker("verify", "success", 0, "yes")); return 0
        if mode == "install": return install_release(arguments, dependencies)
        if mode == "uninstall": return uninstall_release(arguments, dependencies)
        return cli(arguments, dependencies)
    except OpsError as error:
        code = EXIT_USAGE if error.exit_code == EXIT_REFUSAL else error.exit_code
        return emit(mode, error.code, code)
    except Exception:
        return emit(mode, "internal_failure", EXIT_INTERNAL)


if __name__ == "__main__":
    raise SystemExit(main())
