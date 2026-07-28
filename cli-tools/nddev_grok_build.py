#!/usr/bin/env python3
"""Transactional setup manager for an explicit Grok Build home."""

from __future__ import annotations

import argparse
import base64
import binascii
import contextlib
import errno
import fcntl
import hashlib
import http.client
import json
import os
import platform
import re
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, NamedTuple, NoReturn

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="ascii").strip()
PRODUCT_NAME = "nddev-grok-build-app"
SETUP_ROOT = ROOT / "setups"
PROFILE_ROOT = ROOT / "profiles"
BUILDER_ROOT = ROOT / "builder" / "nddev-builder"
CONTENT_SETUP_ORDER = ("nddev-builder",)
PROFILE_ORDER = ("full-auto", "safe")
LEGACY_SETUP_ORDER = ("safe", "balanced", "full-auto")
DEFAULT_SETUP_ID = "nddev-builder"
DEFAULT_PROFILE_ID = "full-auto"
STAMP_NAME = "NDDEV-GROK-BUILD-SETUP.json"
BACKUP_NAME = "NDDEV-GROK-BUILD-BACKUP.json"
SOFTWARE_STAMP_NAME = "NDDEV-GROK-BUILD-SOFTWARE.json"
CONTROL_DIR_NAME = ".nddev-grok-build"
STAMP_SCHEMA_VERSION = 2
LEGACY_STAMP_SCHEMA_VERSION = 1
SOFTWARE_STAMP_SCHEMA_VERSION = 2
MANAGED_BEGIN = "# BEGIN NDDEV-GROK-BUILD MANAGED"
MANAGED_END = "# END NDDEV-GROK-BUILD MANAGED"
OWNER_FILE_MODE = 0o600
OWNER_DIRECTORY_MODE = 0o700
OWNER_EXEC_MODE = 0o700
IMMUTABLE_EXEC_MODE = 0o500
LOCK_PARENT_HELD_MODE = 0o500
LOCK_DIR_NAME = "locks"
LOCK_FILE_NAME = "target.lock"
BOOTSTRAP_LOCK_SCHEMA_VERSION = 1
BOOTSTRAP_LOCK_NAMESPACE = f"{PRODUCT_NAME}:bootstrap-lock:v1"
MANAGED_MAX_BYTES = 8 * 1024 * 1024
METADATA_MAX_BYTES = 256 * 1024
SOFTWARE_MAX_BYTES = 256 * 1024 * 1024
ROLLBACK_MAX_ATTEMPTS = 8
GROK_COMMAND = "grok"
GROK_VERSION = "0.2.112"
GROK_CHANNEL = "stable"
GROK_NPM_PACKAGE = "@xai-official/grok"
GROK_NPM_INTEGRITY = "sha512-dCXAiFHmn3JTOK+vPfCIzzum1GmxPB81NH73yYhqleXx1y/Ks3qjwJ+GeEXmB7eudiap98j9Nj1cDwH4lSuaOw=="
GROK_NPM_SHASUM = "cd103bfeb3d102dff87788a9cbe8d36c293112c8"
GROK_NPM_TARBALL = "https://registry.npmjs.org/@xai-official/grok/-/grok-0.2.112.tgz"
INSTALLER_URL = "https://x.ai/cli/install.sh"
INSTALLER_SHA256 = "0465d810453bbf18608ccae310fa79f4c59ae4a0538bd8a3a374ebce749be952"
INSTALLER_TIMEOUT_SECONDS = 120.0
VERSION_PROBE_TIMEOUT_SECONDS = 15.0
SAFE_SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"
PROVIDER_SECRET_NAMES = {
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "GROK_API_KEY",
    "GROK_DEPLOYMENT_KEY",
    "GROK_PROXY_URL",
    "XAI_API_KEY",
    "XAI_TOKEN",
}
TARGET_SCOPE_FLAGS_WITH_VALUE = {
    "--allow",
    "--allowedTools",
    "--append-system-prompt",
    "--cwd",
    "--deny",
    "--disallowed-tools",
    "--disallowedTools",
    "--effort",
    "--model",
    "--permission-mode",
    "--plugin-dir",
    "--ref",
    "--resume",
    "--rules",
    "--sandbox",
    "--session-id",
    "--system-prompt",
    "--system-prompt-override",
    "--tools",
    "--worktree",
    "-m",
    "-r",
    "-s",
    "-w",
}
TARGET_SCOPE_FLAGS_NO_VALUE = {
    "--always-approve",
    "--continue",
    "--dangerously-skip-permissions",
    "--disable-web-search",
    "--experimental-memory",
    "--fork-session",
    "--no-memory",
    "--no-plan",
    "--no-subagents",
    "--oauth",
    "--trust",
    "--yolo",
    "-c",
}
MUTATING_LAUNCH_TOP_LEVEL_COMMANDS = {
    "auth",
    "config",
    "import",
    "login",
    "logout",
    "setup",
    "update",
}
MUTATING_LAUNCH_SUBCOMMANDS = {
    "mcp": {"add", "remove"},
    "memory": {"clear"},
    "plugin": {"disable", "enable", "install", "uninstall", "update"},
    "sessions": {"delete"},
    "worktree": {"gc", "rm"},
}
MUTATING_LAUNCH_NESTED_SUBCOMMANDS = {
    ("plugin", "marketplace"): {"add", "remove", "update"},
}
BASE_MANAGED_PATHS = ("config.toml", "AGENTS.md")
LEGACY_MANAGED_PATHS = (
    "config.toml",
    "AGENTS.md",
    "skills/nddev-builder/SKILL.md",
    "agents/nddev-builder.md",
    "plugins/nddev-builder/plugin.json",
    "plugins/nddev-builder/skills/nddev-builder/SKILL.md",
    "plugins/nddev-builder/agents/nddev-builder.md",
)
SOFTWARE_ROOT_RELATIVE = ".nddev-software/grok-build"
SOFTWARE_VERSION_BINARY_RELATIVE = f"{SOFTWARE_ROOT_RELATIVE}/versions/{GROK_VERSION}/grok"
SOFTWARE_STAMP_RELATIVE = f"{SOFTWARE_ROOT_RELATIVE}/{SOFTWARE_STAMP_NAME}"
SOFTWARE_MUTATION_PATHS = (
    "bin/grok",
    SOFTWARE_VERSION_BINARY_RELATIVE,
    SOFTWARE_STAMP_RELATIVE,
    SOFTWARE_ROOT_RELATIVE,
)
MERGED_MARKER_PATHS = {"config.toml", "AGENTS.md"}
SETUP_ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
SUPPORTED_HOST_IDS = (
    "macos-arm64",
    "macos-x64",
    "ubuntu-glibc-arm64",
    "ubuntu-glibc-x64",
)
UNSUPPORTED_HOST_CATEGORIES = (
    "windows",
    "non-ubuntu-linux",
    "linux-musl",
    "unsupported-architecture",
)
SUPPORTED_MACHINE_ARCHITECTURES = ("aarch64", "x86_64")
HOST_ARCH_BY_MACHINE_ARCH = {
    "aarch64": "arm64",
    "x86_64": "x64",
}
VENDOR_INSTALLER_ASSET_BY_HOST_ID = {
    "macos-arm64": "grok-0.2.112-macos-aarch64",
    "macos-x64": "grok-0.2.112-macos-x86_64",
    "ubuntu-glibc-arm64": "grok-0.2.112-linux-aarch64",
    "ubuntu-glibc-x64": "grok-0.2.112-linux-x86_64",
}
LINUX_OS_RELEASE_PATHS = (Path("/etc/os-release"), Path("/usr/lib/os-release"))
STAMP_KEYS_V1 = {
    "schema_version",
    "product_name",
    "build_version",
    "setup_id",
    "canonical_target",
    "managed_files",
}
STAMP_KEYS_V2 = {*STAMP_KEYS_V1, "profile_id"}
BACKUP_ENVELOPE_KEYS = {
    "schema_version",
    "product_name",
    "build_version",
    "slot",
    "canonical_target",
    "source_setup_id",
    "source_profile_id",
    "source_stamp_schema",
    "created_at",
    "files",
}
BACKUP_FILE_ENTRY_KEYS = {"payload", "size_bytes", "sha256"}
FORBIDDEN_MANAGED_PATH_ROOTS = {
    CONTROL_DIR_NAME,
    ".nddev-grok-build-runtime",
    ".nddev-software",
}


class GrokBuildSetupError(Exception):
    """Safe user-facing lifecycle failure."""


class RuntimePlatformInfo(NamedTuple):
    system: str
    platform_id: str
    host_id: str
    architecture: str
    host_architecture: str | None
    vendor_installer_asset: str | None
    libc_family: str | None
    libc_version: str | None
    linux_id: str | None
    linux_id_like: tuple[str, ...]
    supported: bool
    reason: str | None


class FileSnapshot(NamedTuple):
    data: bytes | None
    mode: int | None


class TreeEntry(NamedTuple):
    kind: str
    mode: int | None
    data: bytes | None


class BackupTransaction(NamedTuple):
    slot: int
    stage_path: Path
    envelope: dict[str, Any]


class LifecycleSnapshot(NamedTuple):
    files: dict[str, FileSnapshot]
    backup_pool: dict[str, TreeEntry]
    control_tmp: dict[str, TreeEntry]
    launch_images: dict[str, TreeEntry]


class SoftwareSnapshot(NamedTuple):
    software_root: dict[str, TreeEntry]
    software_container_dir: TreeEntry
    managed_binary: FileSnapshot
    managed_bin_dir: TreeEntry
    control_tmp: dict[str, TreeEntry]


def fail(message: str) -> NoReturn:
    raise GrokBuildSetupError(message)


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def toml_string(value: str) -> str:
    return json.dumps(value)


def toml_bool(value: bool) -> str:
    return "true" if value else "false"


def toml_array(values: list[str]) -> str:
    return "[" + ", ".join(toml_string(value) for value in values) + "]"


def require_absolute_target(raw: str) -> Path:
    target = Path(raw)
    if not target.is_absolute():
        fail("target must be an absolute path")
    if target.name in ("", ".", ".."):
        fail("target must name a directory")
    return target


def stat_existing(path: Path, label: str) -> os.stat_result | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode):
        fail(f"{label} must not be a symlink")
    return info


def require_current_user_owner(info: os.stat_result, label: str) -> None:
    get_effective_uid = getattr(os, "geteuid", None)
    if not callable(get_effective_uid):
        return
    if info.st_uid != get_effective_uid():
        fail(f"{label} must be owned by the current user")


def require_real_directory(path: Path, label: str) -> os.stat_result:
    info = stat_existing(path, label)
    if info is None:
        fail(f"{label} is missing")
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    return info


def require_real_parent_directory(path: Path, label: str) -> os.stat_result:
    try:
        info = path.stat()
    except FileNotFoundError:
        fail(f"{label} is missing")
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    return info


def effective_uid() -> int | None:
    get_effective_uid = getattr(os, "geteuid", None)
    if not callable(get_effective_uid):
        return None
    return int(get_effective_uid())


def require_safe_target_parent(path: Path, label: str) -> os.stat_result:
    info = require_real_parent_directory(path, label)
    mode = stat.S_IMODE(info.st_mode)
    if mode & 0o022:
        uid = effective_uid()
        trusted_owner = uid is None or info.st_uid in {0, uid}
        if not (info.st_mode & stat.S_ISVTX and trusted_owner):
            fail(f"{label} must not be group/world writable unless it is a sticky temp directory")
    return info


def validate_target(target: Path, *, create: bool = False) -> Path:
    parent = target.parent
    if create:
        create_missing_directories(missing_directory_chain(parent))
        require_safe_target_parent(parent, "target parent")
    else:
        if not parent.exists():
            return target.resolve(strict=False)
        require_safe_target_parent(parent, "target parent")
    info = stat_existing(target, "target")
    if info is None:
        if not create:
            return target.resolve(strict=False)
        target.mkdir(mode=OWNER_DIRECTORY_MODE)
        target.chmod(OWNER_DIRECTORY_MODE)
        require_private_directory(target, "target")
        return target.resolve()
    require_private_directory(target, "target")
    return target.resolve()


def missing_directory_chain(path: Path) -> list[Path]:
    chain: list[Path] = []
    current = path
    while current != current.parent and not current.exists() and not current.is_symlink():
        chain.append(current)
        current = current.parent
    return chain


def create_missing_directories(chain: list[Path]) -> None:
    for path in reversed(chain):
        try:
            path.mkdir(mode=OWNER_DIRECTORY_MODE)
        except FileExistsError:
            fail(f"directory appeared while creating target parent chain: {path}")
        path.chmod(OWNER_DIRECTORY_MODE)
        require_private_directory(path, f"created target parent {path}")


def remove_created_empty_directories(chain: list[Path]) -> None:
    for path in chain:
        remove_empty_directory_if_created(path, existed_before=False)


def bootstrap_system_root() -> Path:
    raw = Path("/tmp")
    resolved = raw.resolve(strict=True)
    info = stat_existing(resolved, "system bootstrap root")
    if info is None or not stat.S_ISDIR(info.st_mode):
        fail("system bootstrap root must be a real directory")
    if not (info.st_mode & stat.S_ISVTX):
        fail("system bootstrap root must be sticky")
    return resolved


def bootstrap_product_root_path(system_root: Path) -> Path:
    uid = effective_uid()
    if uid is None:
        fail("bootstrap locks require a POSIX effective uid")
    return system_root / f".{PRODUCT_NAME}.uid-{uid}"


def ensure_bootstrap_product_root() -> Path:
    system_root = bootstrap_system_root()
    product_root = bootstrap_product_root_path(system_root)
    info = stat_existing(product_root, "bootstrap lock root")
    if info is None:
        try:
            product_root.mkdir(mode=OWNER_DIRECTORY_MODE)
        except FileExistsError:
            pass
        else:
            product_root.chmod(OWNER_DIRECTORY_MODE)
    require_private_directory(product_root, "bootstrap lock root")
    return product_root


def bootstrap_target_identity(target: Path) -> str:
    if not target.is_absolute():
        fail("target must be an absolute path")
    if target.name in ("", ".", ".."):
        fail("target must name a directory")
    parent = target.parent
    require_safe_target_parent(parent, "target parent")
    resolved_parent = parent.resolve(strict=True)
    return str(resolved_parent / target.name)


def bootstrap_lock_digest(identity: str) -> str:
    payload = f"{BOOTSTRAP_LOCK_NAMESPACE}\n{identity}\n".encode("utf-8")
    return sha256_bytes(payload)


def bootstrap_lock_path(identity: str) -> Path:
    return ensure_bootstrap_product_root() / bootstrap_lock_digest(identity)


def bootstrap_lock_binding(identity: str) -> dict[str, Any]:
    return {
        "schema_version": BOOTSTRAP_LOCK_SCHEMA_VERSION,
        "product_name": PRODUCT_NAME,
        "namespace": BOOTSTRAP_LOCK_NAMESPACE,
        "canonical_target": identity,
        "lock_id": bootstrap_lock_digest(identity),
    }


def validate_bootstrap_lock_binding(value: Any, identity: str) -> None:
    if not isinstance(value, dict):
        fail("bootstrap lock binding must contain a JSON object")
    expected = bootstrap_lock_binding(identity)
    if set(value) != set(expected):
        fail("bootstrap lock binding has invalid keys")
    if value != expected:
        fail("bootstrap lock binding does not match the target")


def expected_bootstrap_lock_binding_bytes(identity: str) -> bytes:
    data = canonical_json(bootstrap_lock_binding(identity))
    if len(data) > METADATA_MAX_BYTES:
        fail("bootstrap lock binding is too large")
    return data


def read_bootstrap_lock_binding(descriptor: int, identity: str) -> bytes | None:
    size = os.fstat(descriptor).st_size
    if size == 0:
        return None
    if size > METADATA_MAX_BYTES:
        fail("bootstrap lock binding is too large")
    os.lseek(descriptor, 0, os.SEEK_SET)
    data = os.read(descriptor, METADATA_MAX_BYTES + 1)
    if len(data) > METADATA_MAX_BYTES:
        fail("bootstrap lock binding is too large")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"bootstrap lock binding is invalid JSON: {exc}")
    validate_bootstrap_lock_binding(value, identity)
    if data != expected_bootstrap_lock_binding_bytes(identity):
        fail("bootstrap lock binding is not canonical")
    return data


def write_bootstrap_lock_binding(descriptor: int, identity: str) -> None:
    data = expected_bootstrap_lock_binding_bytes(identity)
    os.lseek(descriptor, 0, os.SEEK_SET)
    offset = 0
    while offset < len(data):
        written = os.write(descriptor, data[offset:])
        if written <= 0:
            fail("bootstrap lock binding write made no progress")
        offset += written
    os.ftruncate(descriptor, len(data))
    os.fsync(descriptor)
    current = read_bootstrap_lock_binding(descriptor, identity)
    if current != data:
        fail("bootstrap lock binding changed while writing")


def require_bootstrap_lock_descriptor(descriptor: int, path: Path) -> os.stat_result:
    opened = os.fstat(descriptor)
    if not stat.S_ISREG(opened.st_mode):
        fail("bootstrap lock must be a regular file")
    require_current_user_owner(opened, "bootstrap lock")
    if opened.st_nlink != 1:
        fail("bootstrap lock must not be a hardlink")
    if stat.S_IMODE(opened.st_mode) != OWNER_FILE_MODE:
        fail("bootstrap lock must have mode 0600")
    current = stat_existing(path, "bootstrap lock")
    if current is None:
        fail("bootstrap lock disappeared while opening")
    if not stat.S_ISREG(current.st_mode):
        fail("bootstrap lock must be a regular file")
    require_current_user_owner(current, "bootstrap lock")
    if current.st_nlink != 1:
        fail("bootstrap lock must not be a hardlink")
    if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
        fail("bootstrap lock changed while opening")
    if stat.S_IMODE(current.st_mode) != OWNER_FILE_MODE:
        fail("bootstrap lock must have mode 0600")
    return opened


def acquire_bootstrap_lock(target: Path) -> int:
    identity = bootstrap_target_identity(target)
    path = bootstrap_lock_path(identity)
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    created = False
    try:
        descriptor = os.open(path, flags, OWNER_FILE_MODE)
        created = True
        os.fchmod(descriptor, OWNER_FILE_MODE)
    except FileExistsError:
        flags = os.O_RDWR
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            fail(f"bootstrap lock must be a regular owner-private file: {exc}")
    except OSError as exc:
        fail(f"bootstrap lock must be a regular owner-private file: {exc}")
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            fail("bootstrap lock must be a regular file")
        require_current_user_owner(opened, "bootstrap lock")
        if opened.st_nlink != 1:
            fail("bootstrap lock must not be a hardlink")
        if stat.S_IMODE(opened.st_mode) != OWNER_FILE_MODE:
            fail("bootstrap lock must have mode 0600")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}:
                fail(f"target is locked: {path}")
            fail(f"bootstrap lock failed: {exc}")
        opened = require_bootstrap_lock_descriptor(descriptor, path)
        if read_bootstrap_lock_binding(descriptor, identity) is None:
            write_bootstrap_lock_binding(descriptor, identity)
            opened = require_bootstrap_lock_descriptor(descriptor, path)
            if read_bootstrap_lock_binding(
                descriptor, identity
            ) != expected_bootstrap_lock_binding_bytes(identity):
                fail("bootstrap lock binding changed after writing")
        if created:
            os.fsync(descriptor)
        return descriptor
    except BaseException:
        with contextlib.suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
        raise


def release_bootstrap_lock(descriptor: int) -> None:
    with contextlib.suppress(OSError):
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    os.close(descriptor)


@contextlib.contextmanager
def bootstrap_lifecycle_lock(target: Path):
    descriptor = acquire_bootstrap_lock(target)
    try:
        yield
    finally:
        release_bootstrap_lock(descriptor)


def managed_control_dir(target: Path) -> Path:
    return target / CONTROL_DIR_NAME


def backup_pool(target: Path) -> Path:
    return managed_control_dir(target) / "backups"


def legacy_backup_pool(target: Path) -> Path:
    return target.parent / f".{target.name}.nddev-grok-build-backups"


def control_tmp_dir(target: Path) -> Path:
    return managed_control_dir(target) / "tmp"


def lock_parent_dir(target: Path) -> Path:
    return managed_control_dir(target) / LOCK_DIR_NAME


def legacy_lock_path(target: Path) -> Path:
    return managed_control_dir(target) / "lock"


def lock_path(target: Path) -> Path:
    return lock_parent_dir(target) / LOCK_FILE_NAME


def launch_image_dir(target: Path) -> Path:
    return managed_control_dir(target) / "launch-images"


def require_control_directory(path: Path, label: str, *, allow_locked: bool) -> os.stat_result:
    info = stat_existing(path, label)
    if info is None:
        fail(f"{label} is missing")
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    require_current_user_owner(info, label)
    allowed_modes = {OWNER_DIRECTORY_MODE}
    if allow_locked:
        allowed_modes.add(LOCK_PARENT_HELD_MODE)
    if stat.S_IMODE(info.st_mode) not in allowed_modes:
        modes = "0700" if not allow_locked else "0700 or 0500"
        fail(f"{label} must have mode {modes}")
    return info


def require_lock_parent_directory(path: Path, label: str, *, allow_locked: bool) -> os.stat_result:
    info = stat_existing(path, label)
    if info is None:
        fail(f"{label} is missing")
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    require_current_user_owner(info, label)
    allowed_modes = {OWNER_DIRECTORY_MODE}
    if allow_locked:
        allowed_modes.add(LOCK_PARENT_HELD_MODE)
    if stat.S_IMODE(info.st_mode) not in allowed_modes:
        modes = "0700" if not allow_locked else "0700 or 0500"
        fail(f"{label} must have mode {modes}")
    return info


def ensure_lock_control_root(target: Path) -> Path:
    control = managed_control_dir(target)
    info = stat_existing(control, "NDDev control root")
    if info is None:
        control.mkdir(mode=OWNER_DIRECTORY_MODE)
        control.chmod(OWNER_DIRECTORY_MODE)
        require_control_directory(control, "NDDev control root", allow_locked=False)
        return control
    control_info = require_control_directory(control, "NDDev control root", allow_locked=True)
    if stat.S_IMODE(control_info.st_mode) == LOCK_PARENT_HELD_MODE:
        control.chmod(OWNER_DIRECTORY_MODE)
        require_control_directory(control, "NDDev control root", allow_locked=False)
    return control


def recover_legacy_lock_state(target: Path) -> None:
    control = managed_control_dir(target)
    path = legacy_lock_path(target)
    info = stat_existing(path, "target lock")
    if info is None:
        return
    require_current_user_owner(info, "target lock")
    control_info = require_control_directory(control, "NDDev control root", allow_locked=True)
    if stat.S_ISDIR(info.st_mode):
        if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
            fail("legacy target lock directory must have mode 0700")
        if stat.S_IMODE(control_info.st_mode) == LOCK_PARENT_HELD_MODE:
            control.chmod(OWNER_DIRECTORY_MODE)
            require_control_directory(control, "NDDev control root", allow_locked=False)
        try:
            durable_rmdir(path, "legacy target lock directory")
        except OSError as exc:
            fail(f"legacy target lock directory is not safely recoverable: {exc}")
        return
    if not stat.S_ISREG(info.st_mode):
        fail("legacy target lock must be a regular file or empty directory")
    if info.st_nlink != 1:
        fail("legacy target lock must not be a hardlink")
    if stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
        fail("legacy target lock must have mode 0600")
    flags = os.O_RDWR
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            fail("legacy target lock changed while opening")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}:
                fail(f"target is locked: {path}")
            fail(f"legacy target lock recovery failed: {exc}")
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
    if stat.S_IMODE(control_info.st_mode) == LOCK_PARENT_HELD_MODE:
        control.chmod(OWNER_DIRECTORY_MODE)
        require_control_directory(control, "NDDev control root", allow_locked=False)
    durable_unlink(path, "legacy target lock")


def ensure_lock_parent(target: Path) -> None:
    parent = lock_parent_dir(target)
    info = stat_existing(parent, "target lock parent")
    if info is None:
        parent.mkdir(mode=OWNER_DIRECTORY_MODE)
        parent.chmod(OWNER_DIRECTORY_MODE)
        require_lock_parent_directory(parent, "target lock parent", allow_locked=False)
        return
    require_lock_parent_directory(parent, "target lock parent", allow_locked=True)


def open_lock_file(target: Path) -> int:
    path = lock_path(target)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, OWNER_FILE_MODE)
    except OSError as exc:
        parent_info = stat_existing(lock_parent_dir(target), "target lock parent")
        if (
            exc.errno in {errno.EACCES, errno.ENOENT}
            and parent_info is not None
            and stat.S_ISDIR(parent_info.st_mode)
            and stat.S_IMODE(parent_info.st_mode) == LOCK_PARENT_HELD_MODE
            and stat_existing(path, "target lock") is None
        ):
            lock_parent_dir(target).chmod(OWNER_DIRECTORY_MODE)
            require_lock_parent_directory(
                lock_parent_dir(target), "target lock parent", allow_locked=False
            )
            descriptor = os.open(path, flags, OWNER_FILE_MODE)
        else:
            fail(f"target lock must be a regular owner-private file: {exc}")
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            fail("target lock must be a regular file")
        require_current_user_owner(opened, "target lock")
        if opened.st_nlink != 1:
            fail("target lock must not be a hardlink")
        os.fchmod(descriptor, OWNER_FILE_MODE)
        current = stat_existing(path, "target lock")
        if current is None:
            fail("target lock disappeared while opening")
        if not stat.S_ISREG(current.st_mode):
            fail("target lock must be a regular file")
        require_current_user_owner(current, "target lock")
        if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            fail("target lock changed while opening")
        if stat.S_IMODE(current.st_mode) != OWNER_FILE_MODE:
            fail("target lock must have mode 0600")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def acquire_target_lock(target: Path) -> int:
    ensure_lock_control_root(target)
    recover_legacy_lock_state(target)
    ensure_lock_parent(target)
    descriptor = open_lock_file(target)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(descriptor)
        if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}:
            fail(f"target is locked: {lock_path(target)}")
        fail(f"target lock failed: {exc}")
    try:
        current = stat_existing(lock_path(target), "target lock")
        opened = os.fstat(descriptor)
        if current is None or (current.st_dev, current.st_ino) != (
            opened.st_dev,
            opened.st_ino,
        ):
            fail("target lock changed after acquisition")
        if stat.S_IMODE(current.st_mode) != OWNER_FILE_MODE:
            fail("target lock must have mode 0600")
        return descriptor
    except BaseException:
        with contextlib.suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
        raise


def prepare_locked_lock_parent(target: Path) -> None:
    require_control_directory(managed_control_dir(target), "NDDev control root", allow_locked=False)
    parent = lock_parent_dir(target)
    parent_info = require_lock_parent_directory(parent, "target lock parent", allow_locked=True)
    if stat.S_IMODE(parent_info.st_mode) == OWNER_DIRECTORY_MODE:
        parent.chmod(LOCK_PARENT_HELD_MODE)
    require_lock_parent_directory(parent, "target lock parent", allow_locked=True)


def restore_unlocked_lock_parent(target: Path) -> None:
    parent = lock_parent_dir(target)
    if not parent.exists() and not parent.is_symlink():
        return
    require_lock_parent_directory(parent, "target lock parent", allow_locked=True)
    parent.chmod(OWNER_DIRECTORY_MODE)
    require_lock_parent_directory(parent, "target lock parent", allow_locked=False)
    require_control_directory(managed_control_dir(target), "NDDev control root", allow_locked=False)


def remove_created_lock_state_if_empty(target: Path) -> None:
    control = managed_control_dir(target)
    if not target.exists() or target.is_symlink() or not control.exists() or control.is_symlink():
        return
    entries = list(target.iterdir())
    if entries != [control]:
        return
    require_control_directory(control, "NDDev control root", allow_locked=False)
    for directory in (launch_image_dir(target), control_tmp_dir(target), backup_pool(target)):
        remove_empty_directory_if_created(directory, existed_before=False)
    path = lock_path(target)
    if path.exists() or path.is_symlink():
        require_existing_managed_file(
            path, "target lock", max_bytes=METADATA_MAX_BYTES, expected_mode=OWNER_FILE_MODE
        )
        durable_unlink(path, "target lock")
    parent = lock_parent_dir(target)
    if parent.exists() or parent.is_symlink():
        require_lock_parent_directory(parent, "target lock parent", allow_locked=True)
        if stat.S_IMODE(parent.lstat().st_mode) == LOCK_PARENT_HELD_MODE:
            parent.chmod(OWNER_DIRECTORY_MODE)
        remove_empty_directory_if_created(parent, existed_before=False)
    recover_legacy_lock_state(target)
    remove_empty_directory_if_created(control, existed_before=False)


def backup_envelope_path(target: Path, slot: int) -> Path:
    internal = backup_pool(target) / str(slot) / BACKUP_NAME
    if internal.exists() or internal.is_symlink():
        require_private_directory(backup_pool(target), "backup pool")
        require_private_directory(internal.parent, "backup slot")
        require_existing_managed_file(
            internal, BACKUP_NAME, max_bytes=METADATA_MAX_BYTES, expected_mode=OWNER_FILE_MODE
        )
        return internal
    legacy = legacy_backup_pool(target) / str(slot) / BACKUP_NAME
    if legacy.exists() or legacy.is_symlink():
        require_private_directory(legacy_backup_pool(target), "legacy backup pool")
        require_private_directory(legacy.parent, "legacy backup slot")
        require_existing_managed_file(
            legacy, BACKUP_NAME, max_bytes=METADATA_MAX_BYTES, expected_mode=OWNER_FILE_MODE
        )
        return legacy
    return internal


@contextlib.contextmanager
def target_lock(target: Path, *, create: bool):
    created_parent_chain: list[Path] = []
    remove_empty_target = False
    control_preexisting = False
    lock_parent_preexisting = False
    lock_file_preexisting = False
    bootstrap_descriptor: int | None = None
    descriptor: int | None = None
    locked_parent = False
    restore_error: BaseException | None = None
    failed = False
    try:
        bootstrap_descriptor = acquire_bootstrap_lock(target)
        created_parent_chain = missing_directory_chain(target.parent)
        remove_empty_target = create and not (target.exists() or target.is_symlink())
        target = validate_target(target, create=create)
        if not create and not target.exists() and not target.is_symlink():
            fail("target is missing")
        control_preexisting = (
            managed_control_dir(target).exists() or managed_control_dir(target).is_symlink()
        )
        lock_parent_preexisting = (
            lock_parent_dir(target).exists() or lock_parent_dir(target).is_symlink()
        )
        lock_file_preexisting = lock_path(target).exists() or lock_path(target).is_symlink()
        descriptor = acquire_target_lock(target)
        prepare_locked_lock_parent(target)
        locked_parent = True
        try:
            yield target
        except BaseException:
            failed = True
            raise
    finally:
        if locked_parent:
            try:
                restore_unlocked_lock_parent(target)
            except BaseException as exc:
                restore_error = exc
        if descriptor is not None:
            with contextlib.suppress(OSError):
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
        if failed:
            remove_created_target_lock_state(
                target,
                control_preexisting=control_preexisting,
                lock_parent_preexisting=lock_parent_preexisting,
                lock_file_preexisting=lock_file_preexisting,
            )
        prune_empty_control_dirs(target)
        if remove_empty_target:
            remove_created_lock_state_if_empty(target)
            remove_empty_directory_if_created(target, existed_before=False)
        remove_created_empty_directories(created_parent_chain)
        if bootstrap_descriptor is not None:
            release_bootstrap_lock(bootstrap_descriptor)
        if restore_error is not None:
            raise restore_error


def remove_created_target_lock_state(
    target: Path,
    *,
    control_preexisting: bool,
    lock_parent_preexisting: bool,
    lock_file_preexisting: bool,
) -> None:
    if not lock_file_preexisting:
        path = lock_path(target)
        if path.exists() or path.is_symlink():
            require_existing_managed_file(
                path, "target lock", max_bytes=METADATA_MAX_BYTES, expected_mode=OWNER_FILE_MODE
            )
            durable_unlink(path, "target lock")
    if not lock_parent_preexisting:
        parent = lock_parent_dir(target)
        if parent.exists() or parent.is_symlink():
            require_lock_parent_directory(parent, "target lock parent", allow_locked=True)
            if stat.S_IMODE(parent.lstat().st_mode) == LOCK_PARENT_HELD_MODE:
                parent.chmod(OWNER_DIRECTORY_MODE)
            remove_empty_directory_if_created(parent, existed_before=False)
    if not control_preexisting:
        remove_empty_directory_if_created(managed_control_dir(target), existed_before=False)


def prune_empty_control_dirs(target: Path) -> None:
    for directory in (
        launch_image_dir(target),
        control_tmp_dir(target),
        backup_pool(target),
        lock_parent_dir(target),
        managed_control_dir(target),
    ):
        remove_empty_directory_if_created(directory, existed_before=False)


def validate_managed_relative_path(relative: str, label: str) -> str:
    if not isinstance(relative, str) or not relative:
        fail(f"{label} is invalid")
    candidate = Path(relative)
    if candidate.is_absolute() or candidate.as_posix() in {"", "."} or ".." in candidate.parts:
        fail(f"{label} is outside the managed target: {relative}")
    root = candidate.parts[0] if candidate.parts else ""
    if root in FORBIDDEN_MANAGED_PATH_ROOTS:
        fail(f"{label} targets NDDev control or software state: {relative}")
    return candidate.as_posix()


def safe_target_path(target: Path, relative: str) -> Path:
    return target / validate_managed_relative_path(relative, "managed path")


def ensure_real_parent(path: Path, target: Path) -> None:
    relative_parent = path.relative_to(target).parent
    current = target
    for part in relative_parent.parts:
        current = current / part
        info = stat_existing(current, f"managed directory {current}")
        if info is None:
            current.mkdir(mode=OWNER_DIRECTORY_MODE)
            current.chmod(OWNER_DIRECTORY_MODE)
            require_private_directory(current, f"managed directory {current}")
            continue
        if not stat.S_ISDIR(info.st_mode):
            fail(f"managed parent is not a directory: {current}")
        require_current_user_owner(info, f"managed directory {current}")
        if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
            fail(f"managed directory must have mode 0700: {current}")


def require_existing_managed_file(
    path: Path, label: str, *, max_bytes: int, expected_mode: int | None = None
) -> os.stat_result | None:
    info = stat_existing(path, label)
    if info is None:
        return None
    if not stat.S_ISREG(info.st_mode):
        fail(f"{label} must be a regular file")
    require_current_user_owner(info, label)
    if info.st_nlink != 1:
        fail(f"{label} must not be a hardlink")
    if expected_mode is not None and stat.S_IMODE(info.st_mode) != expected_mode:
        fail(f"{label} must have mode {expected_mode:04o}")
    if info.st_size > max_bytes:
        fail(f"{label} is too large")
    return info


def read_existing_file(
    path: Path, *, max_bytes: int, label: str, expected_mode: int | None = None
) -> bytes | None:
    info = require_existing_managed_file(
        path, label, max_bytes=max_bytes, expected_mode=expected_mode
    )
    if info is None:
        return None
    with path.open("rb") as handle:
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        fail(f"{label} is too large")
    return data


def fsync_directory(path: Path, label: str) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        fail(f"{label} parent fsync open failed: {exc}")
    try:
        os.fsync(descriptor)
    except OSError as exc:
        fail(f"{label} parent fsync failed: {exc}")
    finally:
        os.close(descriptor)


def fsync_nearest_existing_parent(path: Path, label: str) -> None:
    current = path.parent
    while current != current.parent and not (current.exists() or current.is_symlink()):
        current = current.parent
    fsync_directory(current, label)


def durable_unlink(path: Path, label: str) -> None:
    info = stat_existing(path, label)
    if info is None:
        return
    if not stat.S_ISREG(info.st_mode):
        fail(f"{label} must be a regular file before unlink")
    require_current_user_owner(info, label)
    if info.st_nlink != 1:
        fail(f"{label} must not be a hardlink before unlink")
    try:
        path.unlink()
    except OSError as exc:
        fail(f"{label} unlink failed: {exc}")
    fsync_directory(path.parent, f"{label} unlink")


def durable_rmdir(path: Path, label: str) -> None:
    info = stat_existing(path, label)
    if info is None:
        return
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory before removal")
    require_current_user_owner(info, label)
    try:
        path.rmdir()
    except OSError as exc:
        fail(f"{label} directory removal failed: {exc}")
    fsync_directory(path.parent, f"{label} directory removal")


def write_temporary_file(temporary: Path, data: bytes, mode: int) -> None:
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        offset = 0
        while offset < len(data):
            written = os.write(descriptor, data[offset:])
            if written <= 0:
                fail(f"temporary write made no progress: {temporary}")
            offset += written
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def replace_file_durable(
    path: Path,
    data: bytes,
    target: Path,
    *,
    mode: int,
    max_bytes: int,
    label: str,
    ensure_parent: Any,
    reader: Any,
    rollback_on_failure: bool = True,
) -> None:
    ensure_parent(path, target)
    before_info = require_existing_managed_file(path, label, max_bytes=max_bytes)
    before_data = reader(path, max_bytes=max_bytes, label=label)
    before_mode = stat.S_IMODE(before_info.st_mode) if before_info is not None else None
    temporary = path.with_name(f".{path.name}.nddev.tmp.{os.getpid()}.{time.time_ns()}")
    replaced = False
    try:
        write_temporary_file(temporary, data, mode)
        os.replace(temporary, path)
        replaced = True
        fsync_directory(path.parent, label)
    except BaseException:
        if replaced and rollback_on_failure:
            restore_atomic_replace_snapshot_retry(
                path,
                FileSnapshot(before_data, before_mode),
                target,
                max_bytes=max_bytes,
                label=f"{label} rollback",
                ensure_parent=ensure_parent,
                reader=reader,
            )
        else:
            remove_file_until_absent_retry(temporary, f"{label} temporary cleanup")
        raise


def atomic_write(path: Path, data: bytes, target: Path) -> None:
    replace_file_durable(
        path,
        data,
        target,
        mode=OWNER_FILE_MODE,
        max_bytes=MANAGED_MAX_BYTES,
        label=str(path),
        ensure_parent=ensure_real_parent,
        reader=read_existing_file,
    )


def atomic_write_with_mode(path: Path, data: bytes, target: Path, mode: int) -> None:
    replace_file_durable(
        path,
        data,
        target,
        mode=mode,
        max_bytes=MANAGED_MAX_BYTES,
        label=str(path),
        ensure_parent=ensure_real_parent,
        reader=read_existing_file,
    )


def read_file_snapshot(
    path: Path, *, max_bytes: int, label: str, expected_mode: int | None = None
) -> FileSnapshot:
    info = require_existing_managed_file(
        path, label, max_bytes=max_bytes, expected_mode=expected_mode
    )
    if info is None:
        return FileSnapshot(None, None)
    data = read_existing_file(path, max_bytes=max_bytes, label=label)
    if data is None:
        fail(f"{label} disappeared while snapshotting")
    return FileSnapshot(data, stat.S_IMODE(info.st_mode))


def file_matches_snapshot(
    path: Path,
    snapshot: FileSnapshot,
    *,
    max_bytes: int,
    label: str,
    reader: Any,
) -> bool:
    if snapshot.data is None:
        return not (path.exists() or path.is_symlink())
    data = reader(path, max_bytes=max_bytes, label=label)
    if data != snapshot.data:
        return False
    info = path.lstat()
    return not stat.S_ISLNK(info.st_mode) and stat.S_IMODE(info.st_mode) == snapshot.mode


def retry_until_exact(label: str, matches: Any, action: Any) -> None:
    first_error: BaseException | None = None
    for _attempt in range(ROLLBACK_MAX_ATTEMPTS):
        try:
            if matches() and first_error is None:
                return
        except BaseException as exc:
            if first_error is None:
                first_error = exc
        try:
            action()
            first_error = None
        except BaseException as exc:
            if first_error is None:
                first_error = exc
    try:
        if matches():
            return
    except BaseException as exc:
        if first_error is None:
            first_error = exc
    if first_error is not None:
        fail(f"{label} did not restore exact pre-state after rollback fault: {first_error}")
    fail(f"{label} did not restore exact pre-state")


def remove_file_until_absent_retry(path: Path, label: str) -> None:
    def matches() -> bool:
        return not (path.exists() or path.is_symlink())

    def action() -> None:
        if not (path.exists() or path.is_symlink()):
            fsync_nearest_existing_parent(path, label)
            return
        durable_unlink(path, label)

    retry_until_exact(label, matches, action)


def restore_atomic_replace_snapshot_retry(
    path: Path,
    snapshot: FileSnapshot,
    target: Path,
    *,
    max_bytes: int,
    label: str,
    ensure_parent: Any,
    reader: Any,
) -> None:
    def matches() -> bool:
        return file_matches_snapshot(
            path, snapshot, max_bytes=max_bytes, label=label, reader=reader
        )

    def action() -> None:
        if snapshot.data is None:
            durable_unlink(path, label)
        else:
            replace_file_durable(
                path,
                snapshot.data,
                target,
                mode=snapshot.mode or OWNER_FILE_MODE,
                max_bytes=max_bytes,
                label=label,
                ensure_parent=ensure_parent,
                reader=reader,
                rollback_on_failure=False,
            )

    retry_until_exact(label, matches, action)


def read_json_file(
    path: Path, *, max_bytes: int, label: str, expected_mode: int | None = None
) -> dict[str, Any]:
    data = read_existing_file(path, max_bytes=max_bytes, label=label, expected_mode=expected_mode)
    if data is None:
        fail(f"{label} is missing")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"{label} is invalid JSON: {exc}")
    if not isinstance(value, dict):
        fail(f"{label} must contain a JSON object")
    return value


def load_setup(setup_id: str) -> dict[str, Any]:
    if not SETUP_ID_PATTERN.fullmatch(setup_id):
        fail(f"invalid setup id: {setup_id}")
    path = SETUP_ROOT / setup_id / "setup.json"
    if not path.is_file():
        fail(f"unknown setup: {setup_id}")
    setup = read_json_file(path, max_bytes=METADATA_MAX_BYTES, label=f"setup {setup_id}")
    if setup.get("id") != setup_id:
        fail(f"setup id mismatch in {path}")
    return setup


def load_profile(profile_id: str) -> dict[str, Any]:
    if not SETUP_ID_PATTERN.fullmatch(profile_id):
        fail(f"invalid profile id: {profile_id}")
    path = PROFILE_ROOT / profile_id / "profile.json"
    if not path.is_file():
        if profile_id in LEGACY_SETUP_ORDER:
            fail(f"legacy setup id is not a permission profile: {profile_id}")
        fail(f"unknown profile: {profile_id}")
    profile = read_json_file(path, max_bytes=METADATA_MAX_BYTES, label=f"profile {profile_id}")
    if profile.get("id") != profile_id:
        fail(f"profile id mismatch in {path}")
    return profile


def list_setups() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for setup_id in CONTENT_SETUP_ORDER:
        setup = load_setup(setup_id)
        items.append(
            {
                "id": setup["id"],
                "display_name": setup["display_name"],
                "description": setup["description"],
                "default_profile": setup["default_profile"],
                "managed_capabilities": setup["managed_capabilities"],
                "native_marketplace": setup["native_marketplace"],
            }
        )
    return items


def list_profiles() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for profile_id in PROFILE_ORDER:
        profile = load_profile(profile_id)
        items.append(
            {
                "id": profile["id"],
                "display_name": profile["display_name"],
                "description": profile["description"],
                "permission_mode": profile["permission_mode"],
                "sandbox_profile": profile["sandbox_profile"],
            }
        )
    return items


def is_legacy_stamp(stamp: dict[str, Any]) -> bool:
    return stamp.get("schema_version") == LEGACY_STAMP_SCHEMA_VERSION


def legacy_profile_for_setup(setup_id: str, requested_profile_id: str | None) -> str:
    if requested_profile_id is not None:
        return requested_profile_id
    if setup_id == "safe":
        return "safe"
    if setup_id == "full-auto":
        return "full-auto"
    fail("legacy balanced setup has no supported native profile; pass --profile explicitly")


def parse_os_release(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[:1] == value[-1:] and value[:1] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def read_linux_os_release(paths: tuple[Path, ...] = LINUX_OS_RELEASE_PATHS) -> dict[str, str]:
    for path in paths:
        with contextlib.suppress(OSError):
            return parse_os_release(path.read_text(encoding="utf-8"))
    return {}


def normalize_architecture(machine: str) -> str:
    normalized = machine.strip().lower().replace("-", "_")
    if normalized in {"arm64", "aarch64"}:
        return "aarch64"
    if normalized in {"amd64", "x64", "x86_64"}:
        return "x86_64"
    return normalized or "unknown"


def normalize_libc_family(name: str) -> str | None:
    normalized = name.strip().lower()
    if not normalized:
        return None
    if "musl" in normalized:
        return "musl"
    if normalized in {"glibc", "gnu", "libc"} or "glibc" in normalized:
        return "glibc"
    return normalized


def current_libc_info(libc_info: tuple[str, str] | None = None) -> tuple[str | None, str | None]:
    raw_family, raw_version = libc_info if libc_info is not None else platform.libc_ver()
    family = normalize_libc_family(raw_family)
    version = raw_version.strip() or None
    return family, version


def supported_host_id(platform_id: str, architecture: str, libc_family: str | None) -> str | None:
    host_architecture = HOST_ARCH_BY_MACHINE_ARCH.get(architecture)
    if host_architecture is None:
        return None
    if platform_id == "macos":
        return f"macos-{host_architecture}"
    if platform_id == "ubuntu" and libc_family == "glibc":
        return f"ubuntu-glibc-{host_architecture}"
    return None


def runtime_platform_result(
    *,
    system: str,
    platform_id: str,
    architecture: str,
    libc_family: str | None = None,
    libc_version: str | None = None,
    linux_id: str | None = None,
    linux_id_like: tuple[str, ...] = (),
    supported: bool,
    reason: str | None = None,
) -> RuntimePlatformInfo:
    host_id = supported_host_id(platform_id, architecture, libc_family)
    return RuntimePlatformInfo(
        system=system,
        platform_id=platform_id,
        host_id=host_id or platform_id,
        architecture=architecture,
        host_architecture=HOST_ARCH_BY_MACHINE_ARCH.get(architecture),
        vendor_installer_asset=(
            VENDOR_INSTALLER_ASSET_BY_HOST_ID.get(host_id) if host_id is not None else None
        ),
        libc_family=libc_family,
        libc_version=libc_version,
        linux_id=linux_id,
        linux_id_like=linux_id_like,
        supported=supported,
        reason=reason,
    )


def runtime_platform_info(
    *,
    system_name: str | None = None,
    machine_name: str | None = None,
    os_release: dict[str, str] | None = None,
    libc_info: tuple[str, str] | None = None,
) -> RuntimePlatformInfo:
    system = system_name if system_name is not None else platform.system()
    architecture = normalize_architecture(
        machine_name if machine_name is not None else platform.machine()
    )
    linux_values = os_release if os_release is not None else {}
    if system == "Linux" and os_release is None:
        linux_values = read_linux_os_release()
    linux_id = linux_values.get("ID") if system == "Linux" else None
    linux_id_like = tuple(linux_values.get("ID_LIKE", "").split()) if system == "Linux" else ()
    libc_family: str | None = None
    libc_version: str | None = None
    if system == "Darwin":
        if architecture not in SUPPORTED_MACHINE_ARCHITECTURES:
            return runtime_platform_result(
                system=system,
                platform_id="unsupported-architecture",
                architecture=architecture,
                supported=False,
                reason=(
                    "unsupported architecture for nddev-grok-build-app runtime management "
                    f"on macos: {architecture}"
                ),
            )
        return runtime_platform_result(
            system=system,
            platform_id="macos",
            architecture=architecture,
            supported=True,
        )
    if system == "Windows":
        return runtime_platform_result(
            system=system,
            platform_id="windows",
            architecture=architecture,
            supported=False,
            reason="unsupported platform for nddev-grok-build-app runtime management: Windows",
        )
    if system == "Linux":
        libc_family, libc_version = current_libc_info(libc_info)
        if architecture not in SUPPORTED_MACHINE_ARCHITECTURES:
            return runtime_platform_result(
                system=system,
                platform_id="unsupported-architecture",
                architecture=architecture,
                libc_family=libc_family,
                libc_version=libc_version,
                linux_id=linux_id,
                linux_id_like=linux_id_like,
                supported=False,
                reason=(
                    "unsupported architecture for nddev-grok-build-app runtime management "
                    f"on Linux: {architecture}"
                ),
            )
        if libc_family != "glibc":
            return runtime_platform_result(
                system=system,
                platform_id="linux-musl",
                architecture=architecture,
                libc_family=libc_family,
                libc_version=libc_version,
                linux_id=linux_id,
                linux_id_like=linux_id_like,
                supported=False,
                reason=(
                    "unsupported Linux libc for nddev-grok-build-app runtime management: "
                    f"{libc_family or 'unknown'}; Ubuntu glibc is required and upstream "
                    "publishes no glibc version floor"
                ),
            )
        if linux_id != "ubuntu":
            return runtime_platform_result(
                system=system,
                platform_id="non-ubuntu-linux",
                architecture=architecture,
                libc_family=libc_family,
                libc_version=libc_version,
                linux_id=linux_id,
                linux_id_like=linux_id_like,
                supported=False,
                reason=(
                    "unsupported Linux distribution for nddev-grok-build-app runtime "
                    f"management: {linux_id or 'unknown'}; Ubuntu is required"
                ),
            )
        return runtime_platform_result(
            system=system,
            platform_id="ubuntu",
            architecture=architecture,
            libc_family=libc_family,
            libc_version=libc_version,
            linux_id=linux_id,
            linux_id_like=linux_id_like,
            supported=True,
        )
    return runtime_platform_result(
        system=system,
        platform_id="unsupported-architecture",
        architecture=architecture,
        supported=False,
        reason=f"unsupported platform for nddev-grok-build-app runtime management: {system}",
    )


def require_supported_runtime_platform(
    info: RuntimePlatformInfo | None = None,
) -> RuntimePlatformInfo:
    checked = info if info is not None else runtime_platform_info()
    if not checked.supported:
        fail(checked.reason or "unsupported platform for nddev-grok-build-app runtime management")
    return checked


def extract_managed_block(text: str) -> str | None:
    begin = text.find(MANAGED_BEGIN)
    if begin < 0:
        return None
    end = text.find(MANAGED_END, begin)
    if end < 0:
        return None
    end += len(MANAGED_END)
    if end < len(text) and text[end : end + 1] == "\n":
        end += 1
    return text[begin:end]


def merge_managed_block(existing: bytes | None, block: str) -> bytes:
    text = existing.decode("utf-8") if existing else ""
    current = extract_managed_block(text)
    if current is None:
        prefix = text
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        if prefix:
            prefix += "\n"
        return (prefix + block).encode("utf-8")
    return text.replace(current, block).encode("utf-8")


def render_config(target: Path, setup: dict[str, Any], profile: dict[str, Any]) -> str:
    marketplace_path = target / "plugins" / "marketplaces" / "nddev-builder"
    capabilities = setup["managed_capabilities"]
    return (
        f"{MANAGED_BEGIN}\n"
        "# Managed by nddev-grok-build-app. Edit outside this block to preserve local state.\n"
        "\n"
        "[models]\n"
        'default = "grok-build"\n'
        'web_search = "grok-4.5"\n'
        "\n"
        "[cli]\n"
        "auto_update = false\n"
        f"channel = {toml_string(GROK_CHANNEL)}\n"
        "\n"
        "[session]\n"
        "load_envrc = false\n"
        "\n"
        "[ui]\n"
        f"permission_mode = {toml_string(profile['permission_mode'])}\n"
        "remember_tool_approvals = false\n"
        'default_selected_permission = "allow_once"\n'
        'screen_mode = "fullscreen"\n'
        "\n"
        "[sandbox]\n"
        f"profile = {toml_string(profile['sandbox_profile'])}\n"
        "auto_allow_bash = false\n"
        "\n"
        "[features]\n"
        f"web_fetch = {toml_bool(bool(capabilities['web_fetch']))}\n"
        f"write_file = {toml_bool(bool(capabilities['write_file']))}\n"
        f"tool_search = {toml_bool(bool(capabilities['tool_search']))}\n"
        f"lsp_tools = {toml_bool(bool(capabilities['lsp_tools']))}\n"
        "\n"
        "[memory]\n"
        f"enabled = {toml_bool(bool(capabilities['memory']))}\n"
        "\n"
        "[subagents]\n"
        f"enabled = {toml_bool(bool(capabilities['subagents']))}\n"
        "\n"
        "[subagents.toggle]\n"
        "explore = true\n"
        "plan = true\n"
        "\n"
        "[plugins]\n"
        'enabled = ["nddev-builder"]\n'
        "\n"
        "[[marketplace.sources]]\n"
        'name = "NDDev Builder"\n'
        f"path = {toml_string(str(marketplace_path))}\n"
        f"{MANAGED_END}\n"
    )


def render_agents_block(setup: dict[str, Any], profile: dict[str, Any]) -> str:
    return (
        f"{MANAGED_BEGIN}\n"
        "# Managed by nddev-grok-build-app. Edit outside this block to preserve local rules.\n"
        "\n"
        "# NDDev Grok Build Setup\n"
        "\n"
        "This Grok Build home is managed by nddev-grok-build-app with content setup "
        f"`{setup['id']}` and permission profile `{profile['id']}`.\n"
        "Use only current Grok Build surfaces documented by xAI: `AGENTS.md`, `.grok/rules/`,\n"
        "`$GROK_HOME/skills/`, `$GROK_HOME/agents/`, hooks, MCP configuration, and plugins.\n"
        "The NDDev Builder plugin is exposed through a target-local Grok marketplace and trusted\n"
        "target-local plugin files. Do not use plugins to deliver native binaries or runtimes.\n"
        f"{MANAGED_END}\n"
    )


def builder_source(relative: str) -> bytes:
    path = BUILDER_ROOT / relative
    if not path.is_file():
        fail(f"builder source missing: {relative}")
    data = path.read_bytes()
    if len(data) > MANAGED_MAX_BYTES:
        fail(f"builder source too large: {relative}")
    return data


def builder_tree(relative_root: str) -> dict[str, bytes]:
    root = BUILDER_ROOT / relative_root
    if not root.is_dir():
        fail(f"builder source directory missing: {relative_root}")
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        info = stat_existing(path, f"builder source {relative_root}/{relative}")
        if info is None:
            continue
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode):
            fail(f"builder source must be a regular file: {relative_root}/{relative}")
        if info.st_size > MANAGED_MAX_BYTES:
            fail(f"builder source too large: {relative_root}/{relative}")
        files[relative] = path.read_bytes()
    return files


def content_managed_paths() -> tuple[str, ...]:
    paths = list(BASE_MANAGED_PATHS)
    plugin_files = builder_tree("plugins/nddev-builder")
    for relative in plugin_files:
        paths.append(f"plugins/nddev-builder/{relative}")
        paths.append(f"plugins/marketplaces/nddev-builder/plugins/nddev-builder/{relative}")
        if relative.startswith(("skills/", "agents/")):
            paths.append(relative)
    for relative in builder_tree(".grok-plugin"):
        paths.append(f"plugins/marketplaces/nddev-builder/.grok-plugin/{relative}")
    return tuple(dict.fromkeys(paths))


def expected_managed_path_set_for_stamp(stamp: dict[str, Any]) -> set[str]:
    if stamp["schema_version"] == LEGACY_STAMP_SCHEMA_VERSION:
        return set(LEGACY_MANAGED_PATHS)
    return set(content_managed_paths())


def desired_files(target: Path, setup: dict[str, Any], profile: dict[str, Any]) -> dict[str, bytes]:
    existing_config = read_existing_file(
        target / "config.toml", max_bytes=MANAGED_MAX_BYTES, label="config.toml"
    )
    existing_agents = read_existing_file(
        target / "AGENTS.md", max_bytes=MANAGED_MAX_BYTES, label="AGENTS.md"
    )
    files = {
        "config.toml": merge_managed_block(existing_config, render_config(target, setup, profile)),
        "AGENTS.md": merge_managed_block(existing_agents, render_agents_block(setup, profile)),
    }
    for relative, data in builder_tree("plugins/nddev-builder").items():
        files[f"plugins/nddev-builder/{relative}"] = data
        files[f"plugins/marketplaces/nddev-builder/plugins/nddev-builder/{relative}"] = data
        if relative.startswith(("skills/", "agents/")):
            files[relative] = data
    for relative, data in builder_tree(".grok-plugin").items():
        files[f"plugins/marketplaces/nddev-builder/.grok-plugin/{relative}"] = data
    return files


def managed_digest_for_bytes(relative: str, data: bytes) -> str:
    if relative in MERGED_MARKER_PATHS:
        block = extract_managed_block(data.decode("utf-8"))
        if block is None:
            return ""
        return sha256_bytes(block.encode("utf-8"))
    return sha256_bytes(data)


def current_managed_digest(target: Path, relative: str) -> str | None:
    data = read_existing_file(
        safe_target_path(target, relative),
        max_bytes=MANAGED_MAX_BYTES,
        label=relative,
        expected_mode=OWNER_FILE_MODE,
    )
    if data is None:
        return None
    digest = managed_digest_for_bytes(relative, data)
    return digest or None


def stamp_path(target: Path) -> Path:
    return target / STAMP_NAME


def validate_stamp_value(stamp: dict[str, Any], target: Path, label: str) -> dict[str, Any]:
    if not isinstance(stamp, dict):
        fail(f"{label} must contain a JSON object")
    if stamp.get("product_name") != PRODUCT_NAME:
        fail(f"{label} belongs to another product")
    canonical = str(validate_target(target, create=False))
    if stamp.get("canonical_target") != canonical:
        fail(f"{label} is bound to a different canonical target")
    schema = stamp.get("schema_version")
    if type(schema) is not int or schema not in {
        LEGACY_STAMP_SCHEMA_VERSION,
        STAMP_SCHEMA_VERSION,
    }:
        fail(f"{label} schema version is unsupported")
    expected_keys = STAMP_KEYS_V1 if schema == LEGACY_STAMP_SCHEMA_VERSION else STAMP_KEYS_V2
    if set(stamp) != expected_keys:
        fail(f"{label} has invalid keys")
    if not isinstance(stamp["build_version"], str) or not stamp["build_version"]:
        fail(f"{label} build_version is invalid")
    setup_id = stamp["setup_id"]
    if not isinstance(setup_id, str) or not SETUP_ID_PATTERN.fullmatch(setup_id):
        fail(f"{label} setup_id is invalid")
    if schema == LEGACY_STAMP_SCHEMA_VERSION:
        if setup_id not in LEGACY_SETUP_ORDER:
            fail(f"{label} legacy setup_id is unsupported")
    elif setup_id not in CONTENT_SETUP_ORDER:
        fail(f"{label} setup_id is unsupported")
    if schema == STAMP_SCHEMA_VERSION:
        profile_id = stamp["profile_id"]
        if not isinstance(profile_id, str) or profile_id not in PROFILE_ORDER:
            fail(f"{label} profile_id is unsupported")
    managed = stamp["managed_files"]
    if not isinstance(managed, dict) or not managed:
        fail(f"{label} managed_files is invalid")
    if set(managed) != expected_managed_path_set_for_stamp(stamp):
        fail(f"{label} managed path set is invalid")
    for relative, expected in managed.items():
        validate_managed_relative_path(relative, f"{label} managed path")
        if relative == STAMP_NAME:
            fail(f"{label} managed_files must not include the stamp")
        if not isinstance(expected, str) or not SHA256_PATTERN.fullmatch(expected):
            fail(f"{label} managed file digest is invalid")
    return stamp


def read_stamp(target: Path) -> dict[str, Any] | None:
    path = stamp_path(target)
    if not path.exists():
        return None
    stamp = read_json_file(
        path, max_bytes=METADATA_MAX_BYTES, label=STAMP_NAME, expected_mode=OWNER_FILE_MODE
    )
    return validate_stamp_value(stamp, target, "stamp")


def drift_for_stamp(target: Path, stamp: dict[str, Any]) -> list[str]:
    drift: list[str] = []
    managed = stamp.get("managed_files")
    if not isinstance(managed, dict):
        fail("stamp managed_files is invalid")
    for relative, expected in managed.items():
        if not isinstance(relative, str) or not isinstance(expected, str):
            fail("stamp managed file digest is invalid")
        current = current_managed_digest(target, relative)
        if current != expected:
            drift.append(relative)
    return drift


def status_payload(target: Path) -> dict[str, Any]:
    with bootstrap_lifecycle_lock(target):
        return status_payload_locked(target)


def status_payload_locked(target: Path) -> dict[str, Any]:
    canonical = validate_target(target, create=False)
    if not target.exists():
        return {
            "state": "absent",
            "managed": False,
            "canonical_target": str(canonical),
            "setup_id": None,
            "profile_id": None,
            "schema_version": None,
            "legacy": False,
            "launchable": False,
            "drift": [],
        }
    require_real_directory(target, "target")
    stamp = read_stamp(target)
    if stamp is None:
        return {
            "state": "unmanaged",
            "managed": False,
            "canonical_target": str(canonical),
            "setup_id": None,
            "profile_id": None,
            "schema_version": None,
            "legacy": False,
            "launchable": False,
            "drift": [],
        }
    if is_legacy_stamp(stamp):
        drift = drift_for_stamp(target, stamp)
        return {
            "state": "legacy-managed",
            "managed": True,
            "canonical_target": str(canonical),
            "setup_id": stamp["setup_id"],
            "profile_id": None,
            "schema_version": stamp["schema_version"],
            "legacy": True,
            "launchable": False,
            "build_version": stamp["build_version"],
            "drift": drift,
            "managed_files": sorted(stamp["managed_files"]),
            "migration_required": True,
            "allowed_legacy_commands": ["status", "migrate", "restore", "remove"],
        }
    drift = drift_for_stamp(target, stamp)
    software = software_status_locked(target)
    return {
        "state": "managed",
        "managed": True,
        "canonical_target": str(canonical),
        "setup_id": stamp["setup_id"],
        "profile_id": stamp["profile_id"],
        "schema_version": stamp["schema_version"],
        "legacy": False,
        "launchable": not drift and software["current"],
        "build_version": stamp["build_version"],
        "drift": drift,
        "managed_files": sorted(stamp["managed_files"]),
        "software_current": software["current"],
        "software_present": software["present"],
        "software_drift": software["drift"],
    }


def snapshot_files(
    target: Path, extra_paths: tuple[str, ...] | list[str] | None = None
) -> dict[str, FileSnapshot]:
    snapshot: dict[str, FileSnapshot] = {}
    paths = list(content_managed_paths())
    if extra_paths is not None:
        paths.extend(extra_paths)
    for relative in (*tuple(dict.fromkeys(paths)), STAMP_NAME):
        snapshot[relative] = read_file_snapshot(
            safe_target_path(target, relative), max_bytes=MANAGED_MAX_BYTES, label=relative
        )
    return snapshot


def managed_files_match_snapshot(target: Path, snapshot: dict[str, FileSnapshot]) -> bool:
    for relative, item in snapshot.items():
        path = safe_target_path(target, relative)
        if not file_matches_snapshot(
            path, item, max_bytes=MANAGED_MAX_BYTES, label=relative, reader=read_existing_file
        ):
            return False
    return True


def restore_snapshot_once(target: Path, snapshot: dict[str, FileSnapshot]) -> None:
    for relative, item in snapshot.items():
        path = safe_target_path(target, relative)
        restore_atomic_replace_snapshot_retry(
            path,
            item,
            target,
            max_bytes=MANAGED_MAX_BYTES,
            label=relative,
            ensure_parent=ensure_real_parent,
            reader=read_existing_file,
        )
    prune_empty_managed_dirs(target)


def restore_snapshot(target: Path, snapshot: dict[str, FileSnapshot]) -> None:
    retry_until_exact(
        "managed file rollback",
        lambda: managed_files_match_snapshot(target, snapshot),
        lambda: restore_snapshot_once(target, snapshot),
    )


def snapshot_tree(root: Path, *, max_bytes: int, label: str) -> dict[str, TreeEntry]:
    if not root.exists() and not root.is_symlink():
        return {".": TreeEntry("absent", None, None)}
    info = stat_existing(root, label)
    if info is None:
        return {".": TreeEntry("absent", None, None)}
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    require_current_user_owner(info, label)
    entries: dict[str, TreeEntry] = {".": TreeEntry("dir", stat.S_IMODE(info.st_mode), None)}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        path_info = stat_existing(path, f"{label}/{relative}")
        if path_info is None:
            continue
        if stat.S_ISDIR(path_info.st_mode):
            require_current_user_owner(path_info, f"{label}/{relative}")
            entries[relative] = TreeEntry("dir", stat.S_IMODE(path_info.st_mode), None)
            continue
        if not stat.S_ISREG(path_info.st_mode):
            fail(f"{label}/{relative} must be a regular file or directory")
        data = read_existing_file(path, max_bytes=max_bytes, label=f"{label}/{relative}")
        if data is None:
            fail(f"{label}/{relative} disappeared while snapshotting")
        entries[relative] = TreeEntry("file", stat.S_IMODE(path_info.st_mode), data)
    return entries


def tree_matches_snapshot(
    root: Path, snapshot: dict[str, TreeEntry], *, max_bytes: int, label: str
) -> bool:
    return snapshot_tree(root, max_bytes=max_bytes, label=label) == snapshot


def snapshot_directory_entry(path: Path, label: str) -> TreeEntry:
    info = stat_existing(path, label)
    if info is None:
        return TreeEntry("absent", None, None)
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    require_current_user_owner(info, label)
    return TreeEntry("dir", stat.S_IMODE(info.st_mode), None)


def directory_entry_matches(path: Path, entry: TreeEntry, label: str) -> bool:
    info = stat_existing(path, label)
    if entry.kind == "absent":
        return info is None
    if info is None or not stat.S_ISDIR(info.st_mode):
        return False
    require_current_user_owner(info, label)
    return stat.S_IMODE(info.st_mode) == entry.mode


def ensure_directory_entry(path: Path, entry: TreeEntry, label: str) -> None:
    if entry.kind == "absent":
        if not (path.exists() or path.is_symlink()):
            fsync_nearest_existing_parent(path, label)
            return
        remove_empty_directory_if_created(path, existed_before=False)
        return
    if entry.kind != "dir" or entry.mode is None:
        fail(f"{label} snapshot is invalid")
    info = stat_existing(path, label)
    if info is None:
        path.mkdir(mode=entry.mode)
        path.chmod(entry.mode)
        fsync_directory(path.parent, label)
        return
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    require_current_user_owner(info, label)
    if stat.S_IMODE(info.st_mode) != entry.mode:
        path.chmod(entry.mode)
        fsync_directory(path, label)


def tree_path(root: Path, relative: str) -> Path:
    return root if relative == "." else root / relative


def remove_tree_once(root: Path, *, max_bytes: int, label: str) -> None:
    if not root.exists() and not root.is_symlink():
        fsync_nearest_existing_parent(root, label)
        return
    entries = snapshot_tree(root, max_bytes=max_bytes, label=label)
    for relative, entry in sorted(
        entries.items(), key=lambda item: len(Path(item[0]).parts), reverse=True
    ):
        path = tree_path(root, relative)
        if entry.kind == "file":
            durable_unlink(path, f"{label}/{relative}")
        elif entry.kind == "dir":
            durable_rmdir(path, f"{label}/{relative}")


def ensure_tree_dir(path: Path, mode: int, label: str) -> None:
    info = stat_existing(path, label)
    if info is None:
        create_missing_directories(missing_directory_chain(path.parent))
        path.mkdir(mode=mode)
        path.chmod(mode)
        fsync_directory(path.parent, label)
        return
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    require_current_user_owner(info, label)
    if stat.S_IMODE(info.st_mode) != mode:
        path.chmod(mode)
        fsync_directory(path, label)


def restore_tree_once(
    root: Path, snapshot: dict[str, TreeEntry], *, max_bytes: int, label: str
) -> None:
    root_entry = snapshot.get(".")
    if root_entry is None:
        fail(f"{label} snapshot is missing the root entry")
    if root_entry.kind == "absent":
        remove_tree_once(root, max_bytes=max_bytes, label=label)
        return
    if root_entry.kind != "dir" or root_entry.mode is None:
        fail(f"{label} snapshot root is invalid")
    ensure_tree_dir(root, root_entry.mode, label)
    current = snapshot_tree(root, max_bytes=max_bytes, label=label)
    expected_paths = set(snapshot)
    for relative, entry in sorted(
        (
            (relative, entry)
            for relative, entry in current.items()
            if relative not in expected_paths
        ),
        key=lambda item: len(Path(item[0]).parts),
        reverse=True,
    ):
        path = tree_path(root, relative)
        if entry.kind == "file":
            durable_unlink(path, f"{label}/{relative}")
        elif entry.kind == "dir":
            durable_rmdir(path, f"{label}/{relative}")
    for relative, entry in sorted(snapshot.items(), key=lambda item: len(Path(item[0]).parts)):
        if entry.kind != "dir":
            continue
        ensure_tree_dir(
            tree_path(root, relative), entry.mode or OWNER_DIRECTORY_MODE, f"{label}/{relative}"
        )
    for relative, entry in sorted(snapshot.items()):
        if entry.kind != "file":
            continue
        if entry.data is None:
            fail(f"{label}/{relative} file snapshot is missing bytes")
        replace_file_durable(
            tree_path(root, relative),
            entry.data,
            root,
            mode=entry.mode or OWNER_FILE_MODE,
            max_bytes=max_bytes,
            label=f"{label}/{relative}",
            ensure_parent=ensure_private_parent,
            reader=read_existing_file,
        )


def restore_tree_retry(
    root: Path, snapshot: dict[str, TreeEntry], *, max_bytes: int, label: str
) -> None:
    retry_until_exact(
        label,
        lambda: tree_matches_snapshot(root, snapshot, max_bytes=max_bytes, label=label),
        lambda: restore_tree_once(root, snapshot, max_bytes=max_bytes, label=label),
    )


def snapshot_lifecycle_state(
    target: Path, extra_paths: tuple[str, ...] | list[str] | None = None
) -> LifecycleSnapshot:
    return LifecycleSnapshot(
        files=snapshot_files(target, extra_paths=extra_paths),
        backup_pool=snapshot_tree(
            backup_pool(target), max_bytes=METADATA_MAX_BYTES, label="backup pool"
        ),
        control_tmp=snapshot_tree(
            control_tmp_dir(target), max_bytes=METADATA_MAX_BYTES, label="control tmp"
        ),
        launch_images=snapshot_tree(
            launch_image_dir(target), max_bytes=SOFTWARE_MAX_BYTES, label="launch images"
        ),
    )


def lifecycle_matches_snapshot(target: Path, snapshot: LifecycleSnapshot) -> bool:
    return (
        managed_files_match_snapshot(target, snapshot.files)
        and tree_matches_snapshot(
            backup_pool(target),
            snapshot.backup_pool,
            max_bytes=METADATA_MAX_BYTES,
            label="backup pool",
        )
        and tree_matches_snapshot(
            control_tmp_dir(target),
            snapshot.control_tmp,
            max_bytes=METADATA_MAX_BYTES,
            label="control tmp",
        )
        and tree_matches_snapshot(
            launch_image_dir(target),
            snapshot.launch_images,
            max_bytes=SOFTWARE_MAX_BYTES,
            label="launch images",
        )
    )


def restore_lifecycle_snapshot_once(target: Path, snapshot: LifecycleSnapshot) -> None:
    restore_snapshot(target, snapshot.files)
    restore_tree_retry(
        backup_pool(target), snapshot.backup_pool, max_bytes=METADATA_MAX_BYTES, label="backup pool"
    )
    restore_tree_retry(
        control_tmp_dir(target),
        snapshot.control_tmp,
        max_bytes=METADATA_MAX_BYTES,
        label="control tmp",
    )
    restore_tree_retry(
        launch_image_dir(target),
        snapshot.launch_images,
        max_bytes=SOFTWARE_MAX_BYTES,
        label="launch images",
    )


def restore_lifecycle_snapshot_retry(target: Path, snapshot: LifecycleSnapshot) -> None:
    retry_until_exact(
        "managed lifecycle rollback",
        lambda: lifecycle_matches_snapshot(target, snapshot),
        lambda: restore_lifecycle_snapshot_once(target, snapshot),
    )


def choose_backup_slot(pool: Path) -> int:
    require_control_directory(pool.parent, "NDDev control root", allow_locked=False)
    if not (pool.exists() or pool.is_symlink()):
        return 0
    require_private_directory(pool, "backup pool")
    for slot in range(10):
        if not (pool / str(slot)).exists():
            return slot
    return min(range(10), key=lambda item: (pool / str(item)).stat().st_mtime_ns)


def backup_file_entry(data: bytes) -> dict[str, Any]:
    return {
        "payload": base64.b64encode(data).decode("ascii"),
        "size_bytes": len(data),
        "sha256": sha256_bytes(data),
    }


def build_backup_envelope(target: Path, stamp: dict[str, Any], slot: int) -> dict[str, Any]:
    files: dict[str, Any] = {}
    managed_paths = sorted(stamp.get("managed_files", {}))
    for relative in (*managed_paths, STAMP_NAME):
        data = read_existing_file(
            safe_target_path(target, relative), max_bytes=MANAGED_MAX_BYTES, label=relative
        )
        if data is None:
            fail(f"backup managed file is missing: {relative}")
        files[relative] = backup_file_entry(data)
    return {
        "schema_version": STAMP_SCHEMA_VERSION,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "slot": slot,
        "canonical_target": str(validate_target(target, create=False)),
        "source_setup_id": stamp["setup_id"],
        "source_profile_id": stamp.get("profile_id"),
        "source_stamp_schema": stamp.get("schema_version"),
        "created_at": int(time.time()),
        "files": files,
    }


def begin_backup_transaction(target: Path, stamp: dict[str, Any]) -> BackupTransaction:
    slot = choose_backup_slot(backup_pool(target))
    envelope = build_backup_envelope(target, stamp, slot)
    require_control_directory(managed_control_dir(target), "NDDev control root", allow_locked=False)
    ensure_private_directory(control_tmp_dir(target), "NDDev control tmp")
    stage_path = control_tmp_dir(target) / (
        f"backup.{slot}.{os.getpid()}.{time.time_ns()}.{BACKUP_NAME}"
    )
    replace_file_durable(
        stage_path,
        canonical_json(envelope),
        control_tmp_dir(target),
        mode=OWNER_FILE_MODE,
        max_bytes=METADATA_MAX_BYTES,
        label="backup stage",
        ensure_parent=ensure_private_parent,
        reader=read_existing_file,
    )
    written = read_json_file(
        stage_path,
        max_bytes=METADATA_MAX_BYTES,
        label="backup stage",
        expected_mode=OWNER_FILE_MODE,
    )
    validate_backup_envelope(target, slot, written)
    return BackupTransaction(slot=slot, stage_path=stage_path, envelope=envelope)


def cleanup_backup_transaction_stage(transaction: BackupTransaction) -> None:
    remove_file_until_absent_retry(transaction.stage_path, "backup stage cleanup")


def commit_backup_transaction(target: Path, transaction: BackupTransaction | None) -> int | None:
    if transaction is None:
        return None
    pool = backup_pool(target)
    require_control_directory(pool.parent, "NDDev control root", allow_locked=False)
    ensure_private_directory(pool, "backup pool")
    slot_dir = pool / str(transaction.slot)
    ensure_private_directory(slot_dir, "backup slot")
    envelope_path = slot_dir / BACKUP_NAME
    expected = canonical_json(transaction.envelope)
    atomic_write(envelope_path, expected, slot_dir)
    actual = read_existing_file(
        envelope_path,
        max_bytes=METADATA_MAX_BYTES,
        label=BACKUP_NAME,
        expected_mode=OWNER_FILE_MODE,
    )
    if actual != expected:
        fail("committed backup bytes do not match the staged envelope")
    written = decode_json_bytes(actual, BACKUP_NAME)
    validate_backup_envelope(target, transaction.slot, written)
    cleanup_backup_transaction_stage(transaction)
    return transaction.slot


def rollback_backup_transaction(target: Path, transaction: BackupTransaction | None) -> None:
    del target
    if transaction is not None:
        cleanup_backup_transaction_stage(transaction)


def create_backup(target: Path, stamp: dict[str, Any]) -> int:
    transaction = begin_backup_transaction(target, stamp)
    slot = commit_backup_transaction(target, transaction)
    if slot is None:
        fail("backup transaction did not commit")
    return slot


def decode_backup_payload(relative: str, encoded: Any) -> bytes:
    if not isinstance(encoded, dict) or set(encoded) != BACKUP_FILE_ENTRY_KEYS:
        fail(f"backup file entry is invalid: {relative}")
    payload = encoded["payload"]
    if not isinstance(payload, str):
        fail(f"backup file payload is invalid: {relative}")
    try:
        data = base64.b64decode(payload.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError) as exc:
        fail(f"backup file payload is not valid base64: {relative}: {exc}")
    if type(encoded["size_bytes"]) is not int or encoded["size_bytes"] != len(data):
        fail(f"backup file size is invalid: {relative}")
    if not isinstance(encoded["sha256"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", encoded["sha256"]
    ):
        fail(f"backup file sha256 is invalid: {relative}")
    if encoded["sha256"] != sha256_bytes(data):
        fail(f"backup file sha256 mismatch: {relative}")
    if len(data) > MANAGED_MAX_BYTES:
        fail(f"backup file payload is too large: {relative}")
    return data


def decode_json_bytes(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"{label} is invalid JSON: {exc}")
    if not isinstance(value, dict):
        fail(f"{label} must contain a JSON object")
    return value


def validate_backup_envelope(
    target: Path, slot: int, envelope: dict[str, Any]
) -> tuple[dict[str, bytes], dict[str, Any]]:
    if set(envelope) != BACKUP_ENVELOPE_KEYS:
        fail("backup envelope has invalid keys")
    if (
        type(envelope["schema_version"]) is not int
        or envelope["schema_version"] != STAMP_SCHEMA_VERSION
    ):
        fail("backup envelope schema version is unsupported")
    if envelope["product_name"] != PRODUCT_NAME:
        fail("backup belongs to another product")
    if not isinstance(envelope["build_version"], str) or not envelope["build_version"]:
        fail("backup build_version is invalid")
    if type(envelope["slot"]) is not int or envelope["slot"] != slot:
        fail("backup slot is invalid")
    if not isinstance(envelope["canonical_target"], str):
        fail("backup canonical_target is invalid")
    if envelope["canonical_target"] != str(validate_target(target, create=False)):
        fail("backup is bound to a different canonical target")
    if not isinstance(envelope["source_setup_id"], str) or not SETUP_ID_PATTERN.fullmatch(
        envelope["source_setup_id"]
    ):
        fail("backup source_setup_id is invalid")
    source_profile_id = envelope["source_profile_id"]
    if source_profile_id is not None and not isinstance(source_profile_id, str):
        fail("backup source_profile_id is invalid")
    if isinstance(source_profile_id, str) and not SETUP_ID_PATTERN.fullmatch(source_profile_id):
        fail("backup source_profile_id is invalid")
    if type(envelope["source_stamp_schema"]) is not int or envelope["source_stamp_schema"] not in {
        LEGACY_STAMP_SCHEMA_VERSION,
        STAMP_SCHEMA_VERSION,
    }:
        fail("backup source stamp schema is unsupported")
    if type(envelope["created_at"]) is not int or envelope["created_at"] < 0:
        fail("backup created_at is invalid")
    files = envelope["files"]
    if not isinstance(files, dict):
        fail("backup files are invalid")
    decoded: dict[str, bytes] = {}
    for relative, encoded in files.items():
        validate_managed_relative_path(relative, "backup file path")
        decoded[relative] = decode_backup_payload(relative, encoded)
    stamp_payload = decoded.get(STAMP_NAME)
    if stamp_payload is None:
        fail("backup stamp payload is missing")
    restored_stamp = validate_stamp_value(
        decode_json_bytes(stamp_payload, "backup restored stamp"),
        target,
        "backup restored stamp",
    )
    if envelope["source_setup_id"] != restored_stamp["setup_id"]:
        fail("backup source_setup_id does not match restored stamp")
    if envelope["source_profile_id"] != restored_stamp.get("profile_id"):
        fail("backup source_profile_id does not match restored stamp")
    if envelope["source_stamp_schema"] != restored_stamp["schema_version"]:
        fail("backup source stamp schema does not match restored stamp")
    expected_paths = {*restored_stamp["managed_files"], STAMP_NAME}
    if set(decoded) != expected_paths:
        fail("backup file set does not match restored stamp")
    if envelope["source_stamp_schema"] == STAMP_SCHEMA_VERSION:
        if not isinstance(source_profile_id, str):
            fail("backup source_profile_id is invalid")
        setup = load_setup(envelope["source_setup_id"])
        profile = load_profile(source_profile_id)
        expected_managed_paths = set(desired_files(target, setup, profile))
    else:
        expected_managed_paths = set(LEGACY_MANAGED_PATHS)
    if set(restored_stamp["managed_files"]) != expected_managed_paths:
        fail("backup managed path set does not match setup/profile")
    for relative, expected_digest in restored_stamp["managed_files"].items():
        payload = decoded.get(relative)
        if payload is None:
            fail(f"backup managed file payload is missing: {relative}")
        try:
            actual_digest = managed_digest_for_bytes(relative, payload)
        except UnicodeDecodeError as exc:
            fail(f"backup managed file payload is invalid UTF-8: {relative}: {exc}")
        if actual_digest != expected_digest:
            fail(f"backup managed file digest mismatch: {relative}")
    return decoded, restored_stamp


def validate_restored_state(target: Path, expected_stamp: dict[str, Any]) -> dict[str, Any]:
    restored_stamp = read_stamp(target)
    if restored_stamp != expected_stamp:
        fail("restored stamp does not match the backup envelope")
    drift = drift_for_stamp(target, restored_stamp)
    if drift:
        fail(f"restored target has drift: {', '.join(drift)}")
    return restored_stamp


def validate_restored_backup_state(
    target: Path, expected_stamp: dict[str, Any], files: dict[str, bytes]
) -> dict[str, Any]:
    restored_stamp = validate_restored_state(target, expected_stamp)
    for relative, expected in files.items():
        actual = read_existing_file(
            safe_target_path(target, relative),
            max_bytes=MANAGED_MAX_BYTES,
            label=relative,
            expected_mode=OWNER_FILE_MODE,
        )
        if actual != expected:
            fail(f"restored file bytes do not match backup envelope: {relative}")
    return restored_stamp


def build_stamp(
    target: Path, setup_id: str, profile_id: str, files: dict[str, bytes]
) -> dict[str, Any]:
    managed = {
        relative: managed_digest_for_bytes(relative, data) for relative, data in files.items()
    }
    return {
        "schema_version": STAMP_SCHEMA_VERSION,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "setup_id": setup_id,
        "profile_id": profile_id,
        "canonical_target": str(validate_target(target, create=False)),
        "managed_files": managed,
    }


def validate_intended_setup_state(
    target: Path, desired_stamp: dict[str, Any], files: dict[str, bytes]
) -> None:
    actual_stamp = read_stamp(target)
    if actual_stamp != desired_stamp:
        fail("managed stamp does not match intended setup state")
    for relative, expected in files.items():
        actual = read_existing_file(
            safe_target_path(target, relative),
            max_bytes=MANAGED_MAX_BYTES,
            label=relative,
            expected_mode=OWNER_FILE_MODE,
        )
        if actual != expected:
            fail(f"managed file bytes do not match intended setup state: {relative}")
    drift = drift_for_stamp(target, desired_stamp)
    if drift:
        fail(f"managed target has drift after write: {', '.join(drift)}")


def restored_files_match(
    target: Path, expected_stamp: dict[str, Any], files: dict[str, bytes]
) -> bool:
    try:
        validate_restored_backup_state(target, expected_stamp, files)
    except GrokBuildSetupError:
        return False
    return True


def validate_removed_setup_state(target: Path, removed: list[str]) -> None:
    if read_stamp(target) is not None:
        fail("managed stamp still exists after setup removal")
    for relative in removed:
        path = safe_target_path(target, relative)
        if relative in MERGED_MARKER_PATHS:
            data = read_existing_file(path, max_bytes=MANAGED_MAX_BYTES, label=relative)
            if data is not None and extract_managed_block(data.decode("utf-8")) is not None:
                fail(f"managed block still exists after setup removal: {relative}")
            continue
        if path.exists() or path.is_symlink():
            fail(f"managed file still exists after setup removal: {relative}")


def changed_paths_for_desired_files(
    target: Path, current: dict[str, Any] | None, files: dict[str, bytes]
) -> list[str]:
    if current is None:
        return sorted(files)
    changed = [
        relative
        for relative, data in files.items()
        if current_managed_digest(target, relative) != managed_digest_for_bytes(relative, data)
    ]
    removed = removed_paths_for_stamp_replacement(current, files)
    return sorted({*changed, *removed})


def removed_paths_for_stamp_replacement(
    current: dict[str, Any] | None, files: dict[str, bytes]
) -> list[str]:
    if current is None:
        return []
    managed = current.get("managed_files")
    if not isinstance(managed, dict):
        fail("stamp managed_files is invalid")
    return sorted(set(managed) - set(files))


def remove_managed_path(target: Path, relative: str) -> None:
    path = safe_target_path(target, relative)
    if relative in MERGED_MARKER_PATHS:
        remove_managed_block_from_target(target, relative)
    else:
        durable_unlink(path, relative)


def write_setup(
    target: Path,
    setup: dict[str, Any],
    profile: dict[str, Any],
    *,
    require_existing: bool = False,
) -> dict[str, Any]:
    with target_lock(target, create=not require_existing) as target:
        current = read_stamp(target)
        if require_existing and current is None:
            fail("switch requires an already managed target")
        if current is not None:
            if is_legacy_stamp(current):
                fail("target uses legacy managed state; run migrate, restore, or remove")
            drift = drift_for_stamp(target, current)
            if drift:
                fail(f"managed target has drift: {', '.join(drift)}")
        files = desired_files(target, setup, profile)
        desired_stamp = build_stamp(target, setup["id"], profile["id"], files)
        changed = changed_paths_for_desired_files(target, current, files)
        removed = removed_paths_for_stamp_replacement(current, files)
        if (
            current is not None
            and current["setup_id"] == setup["id"]
            and current["profile_id"] == profile["id"]
            and not changed
            and not removed
        ):
            return {
                "setup_id": setup["id"],
                "profile_id": profile["id"],
                "changed": [],
                "removed": [],
                "backup_slot": None,
                "target": str(validate_target(target, create=False)),
            }
        snapshot = snapshot_lifecycle_state(
            target, extra_paths=sorted(current["managed_files"]) if current is not None else None
        )
        try:
            backup_transaction = None
            if current is not None and (
                current["setup_id"] != setup["id"] or current["profile_id"] != profile["id"]
            ):
                backup_transaction = begin_backup_transaction(target, current)
            for relative in removed:
                remove_managed_path(target, relative)
            for relative, data in files.items():
                atomic_write(safe_target_path(target, relative), data, target)
            atomic_write(stamp_path(target), canonical_json(desired_stamp), target)
            prune_empty_managed_dirs(target)
            validate_intended_setup_state(target, desired_stamp, files)
            backup_slot = commit_backup_transaction(target, backup_transaction)
            validate_intended_setup_state(target, desired_stamp, files)
        except BaseException:
            restore_lifecycle_snapshot_retry(target, snapshot)
            raise
        return {
            "setup_id": setup["id"],
            "profile_id": profile["id"],
            "changed": changed,
            "removed": removed,
            "backup_slot": backup_slot,
            "target": str(validate_target(target, create=False)),
        }


def migrate_setup(
    target: Path,
    setup: dict[str, Any],
    requested_profile_id: str | None,
) -> dict[str, Any]:
    with target_lock(target, create=False) as target:
        current = read_stamp(target)
        if current is None:
            fail("migrate requires a managed legacy target")
        if not is_legacy_stamp(current):
            fail("target is already using the current setup/profile stamp schema")
        drift = drift_for_stamp(target, current)
        if drift:
            fail(f"managed target has drift: {', '.join(drift)}")
        profile_id = legacy_profile_for_setup(current["setup_id"], requested_profile_id)
        profile = load_profile(profile_id)
        files = desired_files(target, setup, profile)
        desired_stamp = build_stamp(target, setup["id"], profile["id"], files)
        changed = changed_paths_for_desired_files(target, current, files)
        removed = removed_paths_for_stamp_replacement(current, files)
        snapshot = snapshot_lifecycle_state(target, extra_paths=sorted(current["managed_files"]))
        try:
            backup_transaction = begin_backup_transaction(target, current)
            for relative in removed:
                remove_managed_path(target, relative)
            for relative, data in files.items():
                atomic_write(safe_target_path(target, relative), data, target)
            atomic_write(stamp_path(target), canonical_json(desired_stamp), target)
            prune_empty_managed_dirs(target)
            validate_intended_setup_state(target, desired_stamp, files)
            backup_slot = commit_backup_transaction(target, backup_transaction)
            validate_intended_setup_state(target, desired_stamp, files)
        except BaseException:
            restore_lifecycle_snapshot_retry(target, snapshot)
            raise
        return {
            "setup_id": setup["id"],
            "profile_id": profile["id"],
            "source_legacy_setup_id": current["setup_id"],
            "changed": changed,
            "removed": removed,
            "backup_slot": backup_slot,
            "target": str(validate_target(target, create=False)),
        }


def restore_backup(target: Path, slot: int) -> dict[str, Any]:
    if slot < 0 or slot > 9:
        fail("backup slot must be between 0 and 9")
    with target_lock(target, create=False) as target:
        envelope_path = backup_envelope_path(target, slot)
        envelope = read_json_file(
            envelope_path,
            max_bytes=METADATA_MAX_BYTES,
            label=BACKUP_NAME,
            expected_mode=OWNER_FILE_MODE,
        )
        files, expected_stamp = validate_backup_envelope(target, slot, envelope)
        if restored_files_match(target, expected_stamp, files):
            restored_stamp = validate_restored_backup_state(target, expected_stamp, files)
            return {
                "setup_id": restored_stamp["setup_id"],
                "profile_id": restored_stamp.get("profile_id"),
                "legacy": is_legacy_stamp(restored_stamp),
                "backup_slot": slot,
                "target": str(validate_target(target, create=False)),
            }
        snapshot = snapshot_lifecycle_state(target, extra_paths=sorted(files))
        try:
            for relative, data in sorted(files.items()):
                path = safe_target_path(target, relative)
                atomic_write(path, data, target)
            prune_empty_managed_dirs(target)
            restored_stamp = validate_restored_backup_state(target, expected_stamp, files)
        except BaseException:
            restore_lifecycle_snapshot_retry(target, snapshot)
            raise
        return {
            "setup_id": restored_stamp["setup_id"],
            "profile_id": restored_stamp.get("profile_id"),
            "legacy": is_legacy_stamp(restored_stamp),
            "backup_slot": slot,
            "target": str(validate_target(target, create=False)),
        }


def remove_setup(target: Path) -> dict[str, Any]:
    if not target.exists() and not target.is_symlink():
        validate_target(target, create=False)
        return {
            "removed_setup_id": None,
            "changed": [],
            "removed": [],
            "target": str(validate_target(target, create=False)),
        }
    with target_lock(target, create=False) as target:
        stamp = read_stamp(target)
        if stamp is None:
            return {
                "removed_setup_id": None,
                "changed": [],
                "removed": [],
                "target": str(validate_target(target, create=False)),
            }
        drift = drift_for_stamp(target, stamp)
        if drift:
            fail(f"managed target has drift: {', '.join(drift)}")
        removed_setup_id = stamp["setup_id"]
        removed_profile_id = stamp.get("profile_id")
        removed = sorted(stamp["managed_files"])
        snapshot = snapshot_lifecycle_state(target, extra_paths=sorted(stamp["managed_files"]))
        try:
            for relative in removed:
                remove_managed_path(target, relative)
            durable_unlink(stamp_path(target), STAMP_NAME)
            prune_empty_managed_dirs(target)
            validate_removed_setup_state(target, removed)
        except BaseException:
            restore_lifecycle_snapshot_retry(target, snapshot)
            raise
        return {
            "removed_setup_id": removed_setup_id,
            "removed_profile_id": removed_profile_id,
            "removed_legacy": is_legacy_stamp(stamp),
            "changed": removed,
            "removed": removed,
            "target": str(validate_target(target, create=False)),
        }


def remove_managed_block_from_target(target: Path, relative: str) -> None:
    path = safe_target_path(target, relative)
    data = read_existing_file(path, max_bytes=MANAGED_MAX_BYTES, label=relative)
    if data is None:
        return
    text = data.decode("utf-8")
    block = extract_managed_block(text)
    if block is None:
        return
    updated = text.replace(block, "")
    if updated.strip():
        atomic_write(path, updated.encode("utf-8"), target)
    else:
        durable_unlink(path, relative)


def prune_empty_managed_dirs(target: Path) -> None:
    candidates: set[Path] = set()
    for relative in content_managed_paths():
        directory = safe_target_path(target, relative).parent
        while directory != target and target in directory.parents:
            candidates.add(directory)
            directory = directory.parent
    directories = sorted(candidates, key=lambda item: len(item.parts), reverse=True)
    for directory in directories:
        remove_empty_directory_if_created(directory, existed_before=False)


def software_container(target: Path) -> Path:
    return target / ".nddev-software"


def software_root(target: Path) -> Path:
    return software_container(target) / "grok-build"


def software_versions_dir(target: Path) -> Path:
    return software_root(target) / "versions"


def software_version_dir(target: Path) -> Path:
    return software_versions_dir(target) / GROK_VERSION


def software_tree_binary(target: Path) -> Path:
    return software_version_dir(target) / GROK_COMMAND


def managed_grok_path(target: Path) -> Path:
    return target / "bin" / GROK_COMMAND


def software_stamp_path(target: Path) -> Path:
    return software_root(target) / SOFTWARE_STAMP_NAME


def existing_path_label(path: Path, label: str) -> str | None:
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    return label


def software_presence(target: Path) -> list[str]:
    labels = (
        (software_stamp_path(target), SOFTWARE_STAMP_NAME),
        (software_root(target), ".nddev-software/grok-build"),
        (software_version_dir(target), f".nddev-software/grok-build/versions/{GROK_VERSION}"),
        (managed_grok_path(target), "bin/grok"),
    )
    return sorted(label for path, label in labels if existing_path_label(path, label) is not None)


def require_private_directory(path: Path, label: str) -> os.stat_result:
    info = stat_existing(path, label)
    if info is None:
        fail(f"{label} is missing")
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    require_current_user_owner(info, label)
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        fail(f"{label} must have mode 0700")
    return info


def ensure_private_directory(path: Path, label: str) -> None:
    info = stat_existing(path, label)
    if info is None:
        path.mkdir(mode=OWNER_DIRECTORY_MODE)
        path.chmod(OWNER_DIRECTORY_MODE)
        require_private_directory(path, label)
        return
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    require_current_user_owner(info, label)
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        fail(f"{label} must have mode 0700")


def ensure_private_parent(path: Path, target: Path) -> None:
    relative_parent = path.relative_to(target).parent
    current = target
    for part in relative_parent.parts:
        current = current / part
        info = stat_existing(current, f"software directory {current}")
        if info is None:
            current.mkdir(mode=OWNER_DIRECTORY_MODE)
            current.chmod(OWNER_DIRECTORY_MODE)
            require_private_directory(current, f"software parent {current}")
            continue
        if not stat.S_ISDIR(info.st_mode):
            fail(f"software parent is not a directory: {current}")
        require_current_user_owner(info, f"software parent {current}")
        if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
            fail(f"software parent must have mode 0700: {current}")


def require_software_regular_file(
    path: Path, label: str, *, max_bytes: int = SOFTWARE_MAX_BYTES
) -> os.stat_result:
    try:
        info = path.lstat()
    except FileNotFoundError:
        fail(f"{label} is missing")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        fail(f"{label} must be a regular non-symlink file")
    require_current_user_owner(info, label)
    if info.st_nlink != 1:
        fail(f"{label} must not be a hardlink")
    if info.st_size > max_bytes:
        fail(f"{label} is too large")
    return info


def read_software_file(path: Path, label: str, *, max_bytes: int = SOFTWARE_MAX_BYTES) -> bytes:
    before = require_software_regular_file(path, label, max_bytes=max_bytes)
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            fail(f"{label} changed while opening")
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            fail(f"{label} changed to an unsafe file")
        require_current_user_owner(opened, label)
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                fail(f"{label} is too large")
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    final = require_software_regular_file(path, label, max_bytes=max_bytes)
    expected = (before.st_dev, before.st_ino)
    if (after.st_dev, after.st_ino) != expected or (final.st_dev, final.st_ino) != expected:
        fail(f"{label} changed while reading")
    return b"".join(chunks)


def sha256_file_descriptor(descriptor: int, *, max_bytes: int) -> str:
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = os.read(descriptor, 65536)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            fail("Grok Build launch executable is too large")
        digest.update(chunk)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return digest.hexdigest()


def prepare_verified_launch_image(target: Path, expected_sha256: str) -> tuple[Path, int]:
    path = managed_grok_path(target)
    before = require_software_regular_file(path, f"Grok Build managed binary {path}")
    if stat.S_IMODE(before.st_mode) != OWNER_EXEC_MODE:
        fail("Grok Build managed binary must have mode 0700")
    data = read_software_file(path, f"Grok Build managed binary {path}")
    if sha256_bytes(data) != expected_sha256:
        fail("Grok Build managed binary digest changed before launch")
    require_control_directory(managed_control_dir(target), "NDDev control root", allow_locked=False)
    ensure_private_directory(launch_image_dir(target), "Grok Build launch image directory")
    temporary_descriptor, temporary_name = tempfile.mkstemp(
        prefix="launch.", dir=str(launch_image_dir(target))
    )
    temporary = Path(temporary_name)
    descriptor: int | None = None
    try:
        os.write(temporary_descriptor, data)
        os.fchmod(temporary_descriptor, IMMUTABLE_EXEC_MODE)
        os.fsync(temporary_descriptor)
        os.close(temporary_descriptor)
        temporary_descriptor = -1
        launch_image_dir(target).chmod(LOCK_PARENT_HELD_MODE)
        require_lock_parent_directory(
            launch_image_dir(target), "Grok Build launch image directory", allow_locked=True
        )
        flags = os.O_RDONLY
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or stat.S_IMODE(opened.st_mode) != IMMUTABLE_EXEC_MODE:
            fail("Grok Build launch image is not a safe executable file")
        require_current_user_owner(opened, "Grok Build launch image")
        if sha256_file_descriptor(descriptor, max_bytes=SOFTWARE_MAX_BYTES) != expected_sha256:
            fail("Grok Build launch image digest does not match the software stamp")
        return temporary, descriptor
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_descriptor >= 0:
            os.close(temporary_descriptor)
        with contextlib.suppress(FileNotFoundError):
            launch_image_dir(target).chmod(OWNER_DIRECTORY_MODE)
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise


def read_optional_software_file(path: Path, label: str) -> bytes | None:
    if not path.exists() and not path.is_symlink():
        return None
    return read_software_file(path, label)


def read_optional_software_file_for_atomic(
    path: Path, *, max_bytes: int, label: str, expected_mode: int | None = None
) -> bytes | None:
    del expected_mode
    if not path.exists() and not path.is_symlink():
        return None
    return read_software_file(path, label, max_bytes=max_bytes)


def snapshot_optional_software_file(path: Path, label: str) -> FileSnapshot:
    if not path.exists() and not path.is_symlink():
        return FileSnapshot(None, None)
    data = read_software_file(path, label)
    info = require_software_regular_file(path, label)
    return FileSnapshot(data, stat.S_IMODE(info.st_mode))


def software_file_mode_is(path: Path, mode: int) -> bool:
    info = path.lstat()
    return not stat.S_ISLNK(info.st_mode) and stat.S_IMODE(info.st_mode) == mode


def software_atomic_write(path: Path, data: bytes, target: Path, mode: int) -> None:
    replace_file_durable(
        path,
        data,
        target,
        mode=mode,
        max_bytes=SOFTWARE_MAX_BYTES,
        label=str(path),
        ensure_parent=ensure_private_parent,
        reader=read_optional_software_file_for_atomic,
    )


def snapshot_software_state(target: Path) -> SoftwareSnapshot:
    return SoftwareSnapshot(
        software_root=snapshot_tree(
            software_root(target), max_bytes=SOFTWARE_MAX_BYTES, label="software root"
        ),
        software_container_dir=snapshot_directory_entry(
            software_container(target), ".nddev-software"
        ),
        managed_binary=snapshot_optional_software_file(managed_grok_path(target), "bin/grok"),
        managed_bin_dir=snapshot_directory_entry(managed_grok_path(target).parent, "bin"),
        control_tmp=snapshot_tree(
            control_tmp_dir(target), max_bytes=SOFTWARE_MAX_BYTES, label="control tmp"
        ),
    )


def software_matches_snapshot(target: Path, snapshot: SoftwareSnapshot) -> bool:
    return (
        tree_matches_snapshot(
            software_root(target),
            snapshot.software_root,
            max_bytes=SOFTWARE_MAX_BYTES,
            label="software root",
        )
        and directory_entry_matches(
            software_container(target), snapshot.software_container_dir, ".nddev-software"
        )
        and file_matches_snapshot(
            managed_grok_path(target),
            snapshot.managed_binary,
            max_bytes=SOFTWARE_MAX_BYTES,
            label="bin/grok",
            reader=read_optional_software_file_for_atomic,
        )
        and directory_entry_matches(
            managed_grok_path(target).parent, snapshot.managed_bin_dir, "bin"
        )
        and tree_matches_snapshot(
            control_tmp_dir(target),
            snapshot.control_tmp,
            max_bytes=SOFTWARE_MAX_BYTES,
            label="control tmp",
        )
    )


def restore_software_snapshot_once(target: Path, snapshot: SoftwareSnapshot) -> None:
    restore_tree_retry(
        software_root(target),
        snapshot.software_root,
        max_bytes=SOFTWARE_MAX_BYTES,
        label="software root",
    )
    ensure_directory_entry(
        software_container(target), snapshot.software_container_dir, ".nddev-software"
    )
    restore_atomic_replace_snapshot_retry(
        managed_grok_path(target),
        snapshot.managed_binary,
        target,
        max_bytes=SOFTWARE_MAX_BYTES,
        label="bin/grok",
        ensure_parent=ensure_private_parent,
        reader=read_optional_software_file_for_atomic,
    )
    ensure_directory_entry(managed_grok_path(target).parent, snapshot.managed_bin_dir, "bin")
    restore_tree_retry(
        control_tmp_dir(target),
        snapshot.control_tmp,
        max_bytes=SOFTWARE_MAX_BYTES,
        label="control tmp",
    )


def restore_software_snapshot_retry(target: Path, snapshot: SoftwareSnapshot) -> None:
    retry_until_exact(
        "software rollback",
        lambda: software_matches_snapshot(target, snapshot),
        lambda: restore_software_snapshot_once(target, snapshot),
    )


def software_present_paths_from_snapshot(snapshot: SoftwareSnapshot) -> list[str]:
    present: list[str] = []
    if snapshot.managed_binary.data is not None:
        present.append("bin/grok")
    version_binary = snapshot.software_root.get(f"versions/{GROK_VERSION}/grok")
    if version_binary is not None and version_binary.kind == "file":
        present.append(SOFTWARE_VERSION_BINARY_RELATIVE)
    stamp = snapshot.software_root.get(SOFTWARE_STAMP_NAME)
    if stamp is not None and stamp.kind == "file":
        present.append(SOFTWARE_STAMP_RELATIVE)
    root_entry = snapshot.software_root.get(".")
    if root_entry is not None and root_entry.kind == "dir" and not present:
        present.append(SOFTWARE_ROOT_RELATIVE)
    return [path for path in SOFTWARE_MUTATION_PATHS if path in set(present)]


def validate_intended_software_state(target: Path, stamp_bytes: bytes, binary: bytes) -> None:
    final_status = software_status_locked(target)
    if not final_status["installed"]:
        fail(
            "Grok Build software install did not produce structurally complete target-owned software"
        )
    if not final_status["current"]:
        fail("Grok Build software install did not produce current pinned software")
    for path, label in (
        (managed_grok_path(target), "bin/grok"),
        (software_tree_binary(target), SOFTWARE_VERSION_BINARY_RELATIVE),
    ):
        actual = read_software_file(path, label)
        if actual != binary:
            fail(f"Grok Build software bytes do not match intended artifact: {label}")
        info = require_software_regular_file(path, label)
        if stat.S_IMODE(info.st_mode) != OWNER_EXEC_MODE:
            fail(f"Grok Build software mode does not match intended artifact: {label}")
    actual_stamp = read_software_file(
        software_stamp_path(target), SOFTWARE_STAMP_NAME, max_bytes=METADATA_MAX_BYTES
    )
    if actual_stamp != stamp_bytes:
        fail("Grok Build software stamp bytes do not match intended state")


def validate_removed_software_state(target: Path) -> None:
    presence = software_presence(target)
    if presence:
        fail(f"Grok Build software state still exists after removal: {', '.join(presence)}")


def remove_grok_software_state_once(target: Path) -> None:
    restore_tree_retry(
        software_root(target),
        {".": TreeEntry("absent", None, None)},
        max_bytes=SOFTWARE_MAX_BYTES,
        label="software root",
    )
    remove_file_until_absent_retry(managed_grok_path(target), "bin/grok")
    remove_empty_directory_if_created(managed_grok_path(target).parent, existed_before=False)
    remove_empty_directory_if_created(software_container(target), existed_before=False)


def remove_empty_directory_if_created(path: Path, existed_before: bool) -> None:
    if existed_before:
        return
    info = stat_existing(path, f"created directory {path}")
    if info is None:
        return
    if not stat.S_ISDIR(info.st_mode):
        fail(f"created path is not a directory: {path}")
    require_current_user_owner(info, f"created directory {path}")
    try:
        next(path.iterdir())
    except StopIteration:
        durable_rmdir(path, f"created directory {path}")


def read_official_installer_url(source: str, *, max_bytes: int) -> bytes:
    if source != INSTALLER_URL:
        fail("Grok Build installer source must be the pinned official URL")
    request = urllib.request.Request(source, headers={"User-Agent": f"{PRODUCT_NAME}/{VERSION}"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            expected_length_header = response.headers.get("Content-Length")
            expected_length = None
            if expected_length_header is not None:
                try:
                    expected_length = int(expected_length_header)
                except (TypeError, ValueError) as exc:
                    fail(f"official Grok Build installer Content-Length is invalid: {exc}")
                if expected_length < 0:
                    fail("official Grok Build installer Content-Length is invalid")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    fail("Grok Build installer exceeds bounded read limit")
                chunks.append(chunk)
    except GrokBuildSetupError:
        raise
    except (http.client.HTTPException, OSError, TimeoutError, urllib.error.URLError) as exc:
        fail(f"official Grok Build installer fetch failed: {exc}")
    content = b"".join(chunks)
    if expected_length is not None and expected_length != len(content):
        fail("Grok Build installer length changed while reading")
    return content


def minimal_process_env(
    extra_path: str | None = None, *, tmp_dir: Path | None = None
) -> dict[str, str]:
    path = SAFE_SYSTEM_PATH
    if extra_path:
        path = f"{extra_path}:{path}"
    env = {
        "PATH": path,
        "PYTHONDONTWRITEBYTECODE": "1",
        "HOME": "/nonexistent",
        "SHELL": "",
    }
    if tmp_dir is not None:
        env["TMPDIR"] = str(tmp_dir)
    for name in ("LANG", "LC_ALL", "LC_CTYPE", "SYSTEMROOT"):
        value = os.environ.get(name)
        if value:
            env[name] = value
    for name in PROVIDER_SECRET_NAMES:
        env.pop(name, None)
    return env


def read_pinned_installer() -> tuple[bytes, str, str]:
    source = INSTALLER_URL
    installer = read_official_installer_url(source, max_bytes=2 * 1024 * 1024)
    digest = sha256_bytes(installer)
    if digest != INSTALLER_SHA256:
        fail("official Grok Build installer SHA-256 mismatch")
    return installer, digest, source


def software_stamp(
    target: Path,
    *,
    installer_source: str,
    installer_sha256: str,
    binary_sha256: str,
    version_output: str,
) -> dict[str, Any]:
    return {
        "schema_version": SOFTWARE_STAMP_SCHEMA_VERSION,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "canonical_target": str(validate_target(target, create=False)),
        "command": GROK_COMMAND,
        "version": GROK_VERSION,
        "channel": GROK_CHANNEL,
        "installer_url": installer_source,
        "installer_sha256": installer_sha256,
        "installer_exact_version_arg": GROK_VERSION,
        "npm_package": GROK_NPM_PACKAGE,
        "npm_version": GROK_VERSION,
        "npm_integrity": GROK_NPM_INTEGRITY,
        "npm_shasum": GROK_NPM_SHASUM,
        "npm_tarball": GROK_NPM_TARBALL,
        "binary_sha256": binary_sha256,
        "version_output": version_output,
        "installed_at": int(time.time()),
    }


def load_software_stamp(
    target: Path, *, repairable_identity: bool = False
) -> dict[str, Any] | None:
    path = software_stamp_path(target)
    if not path.exists() and not path.is_symlink():
        return None
    info = require_software_regular_file(
        path, f"Grok Build software stamp {path}", max_bytes=METADATA_MAX_BYTES
    )
    if stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
        if repairable_identity:
            return None
        fail("Grok Build software stamp must have mode 0600")
    try:
        value = json.loads(
            read_software_file(
                path, f"Grok Build software stamp {path}", max_bytes=METADATA_MAX_BYTES
            ).decode("utf-8")
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        if repairable_identity:
            return None
        fail(f"Grok Build software stamp is invalid JSON: {exc}")
    if not isinstance(value, dict):
        if repairable_identity:
            return None
        fail("Grok Build software stamp must contain a JSON object")
    required = {
        "schema_version",
        "product_name",
        "build_version",
        "canonical_target",
        "command",
        "version",
        "channel",
        "installer_url",
        "installer_sha256",
        "installer_exact_version_arg",
        "npm_package",
        "npm_version",
        "npm_integrity",
        "npm_shasum",
        "npm_tarball",
        "binary_sha256",
        "version_output",
        "installed_at",
    }
    try:
        if set(value) != required:
            fail("Grok Build software stamp has invalid keys")
        if (
            value["schema_version"] != SOFTWARE_STAMP_SCHEMA_VERSION
            or value["product_name"] != PRODUCT_NAME
            or value["canonical_target"] != str(validate_target(target, create=False))
            or value["command"] != GROK_COMMAND
        ):
            fail("Grok Build software stamp identity is invalid")
        for digest_key in ("installer_sha256", "binary_sha256"):
            if not isinstance(value[digest_key], str) or not re.fullmatch(
                r"[0-9a-f]{64}", value[digest_key]
            ):
                fail(f"Grok Build software stamp {digest_key} must be a SHA-256 digest")
        if not isinstance(value["version"], str):
            fail("Grok Build software stamp version is invalid")
        if (
            value["channel"] != GROK_CHANNEL
            or value["installer_exact_version_arg"] != GROK_VERSION
            or value["npm_package"] != GROK_NPM_PACKAGE
            or value["npm_version"] != GROK_VERSION
            or value["npm_integrity"] != GROK_NPM_INTEGRITY
            or value["npm_shasum"] != GROK_NPM_SHASUM
            or value["npm_tarball"] != GROK_NPM_TARBALL
        ):
            fail("Grok Build software stamp provenance is invalid")
        if (
            not isinstance(value["version_output"], str)
            or GROK_VERSION not in value["version_output"]
        ):
            fail("Grok Build software stamp version output is invalid")
        if not isinstance(value["installed_at"], int):
            fail("Grok Build software stamp installed_at is invalid")
    except GrokBuildSetupError:
        if repairable_identity:
            return None
        raise
    return value


def software_directory_mode_drift(path: Path, label: str) -> str | None:
    if not path.exists() and not path.is_symlink():
        return None
    info = stat_existing(path, label)
    if info is None:
        return None
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    require_current_user_owner(info, label)
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        return f"{label}:mode"
    return None


def software_status(target: Path) -> dict[str, Any]:
    with bootstrap_lifecycle_lock(target):
        return software_status_locked(target)


def software_status_locked(target: Path) -> dict[str, Any]:
    canonical = validate_target(target, create=False)
    base: dict[str, Any] = {
        "schema_version": 1,
        "command": "software-status",
        "target": str(canonical),
        "installed": False,
        "current": False,
        "present": False,
        "presence": [],
        "version": None,
        "expected_version": GROK_VERSION,
        "managed_command": str(managed_grok_path(target).resolve(strict=False)),
        "drift": [],
    }
    if not target.exists() and not target.is_symlink():
        return base
    require_private_directory(target, "target")
    presence = software_presence(target)
    base["present"] = bool(presence)
    base["presence"] = presence
    drift: list[str] = []
    directory_mode_drift = False
    for directory, label in (
        (software_container(target), ".nddev-software"),
        (software_root(target), ".nddev-software/grok-build"),
        (software_versions_dir(target), ".nddev-software/grok-build/versions"),
        (software_version_dir(target), f".nddev-software/grok-build/versions/{GROK_VERSION}"),
        (managed_grok_path(target).parent, "bin"),
    ):
        directory_drift = software_directory_mode_drift(directory, label)
        if directory_drift is not None:
            drift.append(directory_drift)
            directory_mode_drift = True
    stamp_file = software_stamp_path(target)
    if stamp_file.exists() or stamp_file.is_symlink():
        stamp_info = require_software_regular_file(
            stamp_file, f"Grok Build software stamp {stamp_file}", max_bytes=METADATA_MAX_BYTES
        )
        if stat.S_IMODE(stamp_info.st_mode) != OWNER_FILE_MODE:
            drift.append("software-stamp:mode")
    stamp = load_software_stamp(target, repairable_identity=True)
    if stamp is None:
        for partial_file, label in (
            (managed_grok_path(target), "bin/grok"),
            (
                software_tree_binary(target),
                f".nddev-software/grok-build/versions/{GROK_VERSION}/grok",
            ),
        ):
            if partial_file.exists() or partial_file.is_symlink():
                read_software_file(partial_file, f"Grok Build partial software file {partial_file}")
                if not software_file_mode_is(partial_file, OWNER_EXEC_MODE):
                    drift.append(f"{label}:mode")
        if presence:
            drift.append("software-stamp")
    else:
        binary = read_optional_software_file(
            managed_grok_path(target), f"Grok Build managed binary {managed_grok_path(target)}"
        )
        version_binary = read_optional_software_file(
            software_tree_binary(target),
            f"Grok Build version binary {software_tree_binary(target)}",
        )
        binary_ok = binary is not None and sha256_bytes(binary) == stamp["binary_sha256"]
        version_ok = (
            version_binary is not None and sha256_bytes(version_binary) == stamp["binary_sha256"]
        )
        binary_mode_ok = binary is not None and software_file_mode_is(
            managed_grok_path(target), OWNER_EXEC_MODE
        )
        version_mode_ok = version_binary is not None and software_file_mode_is(
            software_tree_binary(target), OWNER_EXEC_MODE
        )
        if not binary_ok:
            drift.append("bin/grok")
        elif not binary_mode_ok:
            drift.append("bin/grok:mode")
        if not version_ok:
            drift.append(f".nddev-software/grok-build/versions/{GROK_VERSION}/grok")
        elif not version_mode_ok:
            drift.append(f".nddev-software/grok-build/versions/{GROK_VERSION}/grok:mode")
        installed = (
            binary_ok
            and version_ok
            and binary_mode_ok
            and version_mode_ok
            and not directory_mode_drift
        )
        expected = {
            "build_version": VERSION,
            "version": GROK_VERSION,
            "channel": GROK_CHANNEL,
            "installer_url": INSTALLER_URL,
            "installer_sha256": INSTALLER_SHA256,
            "installer_exact_version_arg": GROK_VERSION,
            "npm_package": GROK_NPM_PACKAGE,
            "npm_version": GROK_VERSION,
            "npm_integrity": GROK_NPM_INTEGRITY,
            "npm_shasum": GROK_NPM_SHASUM,
            "npm_tarball": GROK_NPM_TARBALL,
        }
        for key, expected_value in expected.items():
            if stamp[key] != expected_value:
                drift.append(key)
        base["installed"] = installed
        base["version"] = stamp["version"]
    base["drift"] = drift
    base["current"] = bool(base["installed"]) and not drift
    return base


def validate_safe_software_presence(target: Path) -> None:
    for directory, label in (
        (managed_grok_path(target).parent, "bin"),
        (software_container(target), ".nddev-software"),
        (software_root(target), ".nddev-software/grok-build"),
        (software_versions_dir(target), ".nddev-software/grok-build/versions"),
        (software_version_dir(target), f".nddev-software/grok-build/versions/{GROK_VERSION}"),
    ):
        if directory.exists() or directory.is_symlink():
            require_private_directory(directory, label)
    for file_path, label, mode in (
        (managed_grok_path(target), "bin/grok", OWNER_EXEC_MODE),
        (
            software_tree_binary(target),
            f".nddev-software/grok-build/versions/{GROK_VERSION}/grok",
            OWNER_EXEC_MODE,
        ),
        (software_stamp_path(target), SOFTWARE_STAMP_NAME, OWNER_FILE_MODE),
    ):
        if file_path.exists() or file_path.is_symlink():
            info = require_software_regular_file(file_path, label, max_bytes=SOFTWARE_MAX_BYTES)
            if stat.S_IMODE(info.st_mode) != mode:
                fail(f"{label} must have mode {mode:04o}")


def run_vendor_installer(
    installer: bytes, installer_source: str, installer_sha256: str, target: Path
) -> dict[str, Any]:
    require_control_directory(managed_control_dir(target), "NDDev control root", allow_locked=False)
    ensure_private_directory(control_tmp_dir(target), "NDDev control tmp")
    with tempfile.TemporaryDirectory(
        prefix="installer.", dir=str(control_tmp_dir(target))
    ) as stage_raw:
        stage = Path(stage_raw)
        home = stage / "home"
        bin_dir = stage / "bin"
        grok_home = stage / "grok-home"
        tmp_dir = stage / "tmp"
        for directory in (home, bin_dir, grok_home, tmp_dir):
            directory.mkdir(mode=OWNER_DIRECTORY_MODE)
            directory.chmod(OWNER_DIRECTORY_MODE)
        installer_path = stage / "install.sh"
        installer_path.write_bytes(installer)
        installer_path.chmod(OWNER_EXEC_MODE)
        env = minimal_process_env(str(bin_dir), tmp_dir=tmp_dir)
        env.update(
            {
                "HOME": str(home),
                "GROK_HOME": str(grok_home),
                "GROK_BIN_DIR": str(bin_dir),
                "GROK_CHANNEL": GROK_CHANNEL,
                "SHELL": "",
            }
        )
        try:
            completed = subprocess.run(
                ["bash", str(installer_path), GROK_VERSION],
                cwd=stage,
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=INSTALLER_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as exc:
            missing = exc.filename or "bash"
            fail(f"Grok Build vendor installer runner is missing: {missing}")
        except subprocess.TimeoutExpired:
            fail("Grok Build vendor installer timed out")
        if completed.returncode != 0:
            fail(
                "Grok Build vendor installer failed: "
                + (completed.stderr or completed.stdout).strip()
            )
        staging_binary = bin_dir / GROK_COMMAND
        stage_resolved = stage.resolve(strict=True)
        resolved_binary = staging_binary.resolve(strict=True)
        if stage_resolved not in resolved_binary.parents:
            fail("Grok Build installer binary escaped the staging directory")
        binary = read_software_file(resolved_binary, f"Grok Build staging binary {resolved_binary}")
        probe_env = minimal_process_env(str(bin_dir), tmp_dir=tmp_dir)
        probe_env["HOME"] = str(stage / "probe-home")
        Path(probe_env["HOME"]).mkdir(mode=OWNER_DIRECTORY_MODE)
        try:
            probe = subprocess.run(
                [str(resolved_binary), "--version"],
                cwd=stage,
                env=probe_env,
                text=True,
                input="",
                capture_output=True,
                check=False,
                timeout=VERSION_PROBE_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as exc:
            missing = exc.filename or str(resolved_binary)
            fail(f"Grok Build version probe executable is missing: {missing}")
        except subprocess.TimeoutExpired:
            fail("Grok Build version probe timed out")
        version_output = (probe.stdout + probe.stderr).strip()
        if probe.returncode != 0 or GROK_VERSION not in version_output:
            fail("Grok Build staging binary did not report the pinned version")
        return {
            "binary": binary,
            "binary_sha256": sha256_bytes(binary),
            "installer_source": installer_source,
            "installer_sha256": installer_sha256,
            "version_output": version_output,
        }


def install_grok_software(target: Path, command: str) -> dict[str, Any]:
    require_supported_runtime_platform()
    before_target_exists = target.exists() or target.is_symlink()
    with target_lock(target, create=command == "install-cli") as target:
        try:
            status = software_status_locked(target)
            if command == "install-cli" and status["present"]:
                fail(
                    "install-cli requires absent target-owned Grok Build software presence; use update-cli"
                )
            if command == "update-cli" and not status["present"]:
                fail("update-cli requires existing target-owned Grok Build software presence")
            if command == "update-cli" and status["current"]:
                return {
                    "schema_version": 1,
                    "command": command,
                    "operation": "current",
                    "target": str(validate_target(target, create=False)),
                    "version": GROK_VERSION,
                    "current": True,
                    "changed": [],
                    "managed_command": str(managed_grok_path(target).resolve(strict=False)),
                }
            validate_safe_software_presence(target)
            snapshot = snapshot_software_state(target)
            try:
                installer, installer_sha256, installer_source = read_pinned_installer()
                artifact = run_vendor_installer(
                    installer, installer_source, installer_sha256, target
                )
                stamp_bytes = canonical_json(
                    software_stamp(
                        target,
                        installer_source=artifact["installer_source"],
                        installer_sha256=artifact["installer_sha256"],
                        binary_sha256=artifact["binary_sha256"],
                        version_output=artifact["version_output"],
                    )
                )
                ensure_private_directory(software_container(target), ".nddev-software")
                ensure_private_directory(software_root(target), ".nddev-software/grok-build")
                ensure_private_directory(
                    software_versions_dir(target), ".nddev-software/grok-build/versions"
                )
                ensure_private_directory(
                    software_version_dir(target),
                    f".nddev-software/grok-build/versions/{GROK_VERSION}",
                )
                software_atomic_write(
                    software_tree_binary(target), artifact["binary"], target, OWNER_EXEC_MODE
                )
                software_atomic_write(
                    managed_grok_path(target), artifact["binary"], target, OWNER_EXEC_MODE
                )
                software_atomic_write(
                    software_stamp_path(target), stamp_bytes, target, OWNER_FILE_MODE
                )
                restore_tree_retry(
                    control_tmp_dir(target),
                    snapshot.control_tmp,
                    max_bytes=SOFTWARE_MAX_BYTES,
                    label="control tmp",
                )
                validate_intended_software_state(target, stamp_bytes, artifact["binary"])
            except BaseException:
                restore_software_snapshot_retry(target, snapshot)
                raise
            final_status = software_status_locked(target)
            return {
                "schema_version": 1,
                "command": command,
                "operation": "install" if command == "install-cli" else "update",
                "target": str(validate_target(target, create=False)),
                "version": GROK_VERSION,
                "current": final_status["current"],
                "changed": [
                    "bin/grok",
                    SOFTWARE_VERSION_BINARY_RELATIVE,
                    SOFTWARE_STAMP_RELATIVE,
                ],
                "installer_sha256": artifact["installer_sha256"],
                "binary_sha256": artifact["binary_sha256"],
                "managed_command": str(managed_grok_path(target).resolve(strict=False)),
            }
        except BaseException:
            remove_empty_directory_if_created(target, before_target_exists)
            raise


def remove_grok_software(target: Path) -> dict[str, Any]:
    require_supported_runtime_platform()
    if not target.exists() and not target.is_symlink():
        return {
            "schema_version": 1,
            "command": "remove-cli",
            "operation": "absent",
            "target": str(validate_target(target, create=False)),
            "version": GROK_VERSION,
            "current": False,
            "changed": [],
            "removed": [],
            "managed_command": str(managed_grok_path(target).resolve(strict=False)),
        }
    with target_lock(target, create=False) as target:
        status = software_status_locked(target)
        if not status["present"]:
            return {
                "schema_version": 1,
                "command": "remove-cli",
                "operation": "absent",
                "target": str(validate_target(target, create=False)),
                "version": GROK_VERSION,
                "current": False,
                "changed": [],
                "removed": [],
                "managed_command": str(managed_grok_path(target).resolve(strict=False)),
            }
        validate_safe_software_presence(target)
        snapshot = snapshot_software_state(target)
        removed = software_present_paths_from_snapshot(snapshot)
        try:
            remove_grok_software_state_once(target)
            restore_tree_retry(
                control_tmp_dir(target),
                snapshot.control_tmp,
                max_bytes=SOFTWARE_MAX_BYTES,
                label="control tmp",
            )
            validate_removed_software_state(target)
        except BaseException:
            restore_software_snapshot_retry(target, snapshot)
            raise
        return {
            "schema_version": 1,
            "command": "remove-cli",
            "operation": "remove",
            "target": str(validate_target(target, create=False)),
            "version": GROK_VERSION,
            "current": False,
            "changed": removed,
            "removed": removed,
            "managed_command": str(managed_grok_path(target).resolve(strict=False)),
        }


def plan_payload(target: Path, setup: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    with bootstrap_lifecycle_lock(target):
        status = status_payload_locked(target)
        canonical_target = validate_target(target, create=False)
        current = read_stamp(canonical_target) if status["managed"] else None
        files = desired_files(canonical_target, setup, profile)
        changed = changed_paths_for_desired_files(canonical_target, current, files)
        removed = removed_paths_for_stamp_replacement(current, files)
    operation = "install"
    backup_required = False
    if status["managed"]:
        if status.get("legacy"):
            operation = "migrate"
            backup_required = True
        else:
            operation = (
                "update"
                if status["setup_id"] == setup["id"] and status["profile_id"] == profile["id"]
                else "switch"
            )
            backup_required = (
                status["setup_id"] != setup["id"] or status["profile_id"] != profile["id"]
            )
    return {
        "operation": operation,
        "setup_id": setup["id"],
        "profile_id": profile["id"],
        "target": str(canonical_target),
        "current_setup_id": status["setup_id"],
        "current_profile_id": status["profile_id"],
        "current_schema_version": status["schema_version"],
        "drift": status["drift"],
        "changed": changed,
        "removed": removed,
        "backup_required": backup_required,
        "mutates": False,
    }


def child_args_use_target_scope_overrides(child_args: list[str]) -> str | None:
    for arg in child_args:
        if arg == "--":
            return None
        if arg in TARGET_SCOPE_FLAGS_NO_VALUE:
            return arg
        if arg in TARGET_SCOPE_FLAGS_WITH_VALUE:
            return arg
        for flag in TARGET_SCOPE_FLAGS_WITH_VALUE:
            if arg.startswith(f"{flag}="):
                return flag
    return None


def launch_command_tokens(child_args: list[str]) -> list[str]:
    tokens: list[str] = []
    skip_next = False
    for arg in child_args:
        if skip_next:
            skip_next = False
            continue
        if arg == "--":
            continue
        if arg in TARGET_SCOPE_FLAGS_WITH_VALUE:
            skip_next = True
            continue
        if arg.startswith("-"):
            continue
        tokens.append(arg)
    return tokens


def managed_launch_mutation(child_args: list[str]) -> str | None:
    tokens = launch_command_tokens(child_args)
    if not tokens:
        return None
    first = tokens[0]
    if first in MUTATING_LAUNCH_TOP_LEVEL_COMMANDS:
        return first
    if len(tokens) >= 2 and tokens[1] in MUTATING_LAUNCH_SUBCOMMANDS.get(first, set()):
        return f"{first} {tokens[1]}"
    if (
        len(tokens) >= 3
        and (first, tokens[1]) in MUTATING_LAUNCH_NESTED_SUBCOMMANDS
        and tokens[2] in MUTATING_LAUNCH_NESTED_SUBCOMMANDS[(first, tokens[1])]
    ):
        return f"{first} {tokens[1]} {tokens[2]}"
    return None


def launch(target: Path, child_args: list[str]) -> int:
    require_supported_runtime_platform()
    override = child_args_use_target_scope_overrides(child_args)
    if override is not None:
        fail(f"launch child arguments must not override target-owned Grok Build scope: {override}")
    mutation = managed_launch_mutation(child_args)
    if mutation is not None:
        fail(f"launch denied for Grok Build managed-state mutation: {mutation}")
    with target_lock(target, create=False) as target:
        status = status_payload_locked(target)
        if not status["managed"]:
            fail("launch requires a managed target")
        if status.get("legacy"):
            fail("launch denied for legacy managed state; run migrate, restore, or remove")
        if status["drift"]:
            fail(f"managed target has drift: {', '.join(status['drift'])}")
        software = software_status_locked(target)
        if not software["installed"] or not software["current"]:
            fail("launch requires current target-owned Grok Build software")
        software_stamp_value = load_software_stamp(target)
        if software_stamp_value is None:
            fail("launch requires a current target-owned Grok Build software stamp")
        setup = load_setup(str(status["setup_id"]))
        profile = load_profile(str(status["profile_id"]))
        capabilities = setup["managed_capabilities"]
        canonical = validate_target(target, create=False)
        runtime_root = canonical / ".nddev-grok-build-runtime"
        home = runtime_root / "home"
        tmp = runtime_root / "tmp"
        xdg_config = home / ".config"
        xdg_cache = home / ".cache"
        xdg_data = home / ".local" / "share"
        xdg_state = home / ".local" / "state"
        create_missing_directories(missing_directory_chain(home))
        create_missing_directories(missing_directory_chain(tmp))
        require_private_directory(runtime_root, "Grok Build runtime root")
        require_private_directory(home, "Grok Build runtime HOME")
        require_private_directory(tmp, "Grok Build runtime TMPDIR")
        child_env: dict[str, str] = {
            "HOME": str(home),
            "GROK_HOME": str(canonical),
            "GROK_DISABLE_AUTOUPDATER": "1",
            "GROK_SANDBOX": str(profile["sandbox_profile"]),
            "GROK_SUBAGENTS": "1" if capabilities["subagents"] else "0",
            "GROK_WEB_FETCH": "1" if capabilities["web_fetch"] else "0",
            "GROK_MEMORY": "1" if capabilities["memory"] else "0",
            "GROK_LSP_TOOLS": "1" if capabilities["lsp_tools"] else "0",
            "GROK_WRITE_FILE": "1" if capabilities["write_file"] else "0",
            "GROK_TOOL_SEARCH": "1" if capabilities["tool_search"] else "0",
            "PATH": SAFE_SYSTEM_PATH,
            "TMPDIR": str(tmp),
            "XDG_CACHE_HOME": str(xdg_cache),
            "XDG_CONFIG_HOME": str(xdg_config),
            "XDG_DATA_HOME": str(xdg_data),
            "XDG_STATE_HOME": str(xdg_state),
        }
        for name in ("TERM", "COLORTERM", "LANG", "LC_ALL", "LC_CTYPE", "SYSTEMROOT"):
            value = os.environ.get(name)
            if value:
                child_env[name] = value
        for name in PROVIDER_SECRET_NAMES:
            child_env.pop(name, None)
        launch_image, descriptor = prepare_verified_launch_image(
            target, str(software_stamp_value["binary_sha256"])
        )
        try:
            expected_image = os.fstat(descriptor)
            process = subprocess.Popen(
                [str(launch_image), *child_args],
                env=child_env,
                close_fds=True,
            )
            current_image = require_software_regular_file(
                launch_image, "Grok Build launch image", max_bytes=SOFTWARE_MAX_BYTES
            )
            if (current_image.st_dev, current_image.st_ino) != (
                expected_image.st_dev,
                expected_image.st_ino,
            ):
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                process.wait()
                fail("Grok Build launch image changed before child execution")
            current_digest = sha256_bytes(
                read_software_file(launch_image, "Grok Build launch image")
            )
            if current_digest != software_stamp_value["binary_sha256"]:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                process.wait()
                fail("Grok Build launch image digest changed before child execution")
            return int(process.wait())
        finally:
            os.close(descriptor)
            image_parent = launch_image.parent
            if image_parent.exists() or image_parent.is_symlink():
                require_lock_parent_directory(
                    image_parent, "Grok Build launch image directory", allow_locked=True
                )
                image_parent.chmod(OWNER_DIRECTORY_MODE)
                require_lock_parent_directory(
                    image_parent, "Grok Build launch image directory", allow_locked=False
                )
            with contextlib.suppress(FileNotFoundError):
                launch_image.unlink()
            with contextlib.suppress(FileNotFoundError, OSError):
                image_parent.rmdir()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--json", action="store_true")
    for name in (
        "status",
        "remove",
        "software-status",
        "install-cli",
        "update-cli",
        "remove-cli",
    ):
        command = subparsers.add_parser(name)
        command.add_argument("--target", required=True)
        command.add_argument("--json", action="store_true")
    for name in ("plan", "install", "switch"):
        command = subparsers.add_parser(name)
        command.add_argument("--setup", default=DEFAULT_SETUP_ID)
        command.add_argument("--profile", default=DEFAULT_PROFILE_ID)
        command.add_argument("--target", required=True)
        command.add_argument("--json", action="store_true")
    migrate = subparsers.add_parser("migrate")
    migrate.add_argument("--setup", default=DEFAULT_SETUP_ID)
    migrate.add_argument("--profile")
    migrate.add_argument("--target", required=True)
    migrate.add_argument("--json", action="store_true")
    restore = subparsers.add_parser("restore")
    restore.add_argument("--backup", required=True, type=int)
    restore.add_argument("--target", required=True)
    restore.add_argument("--json", action="store_true")
    launch_parser = subparsers.add_parser("launch")
    launch_parser.add_argument("--target", required=True)
    launch_parser.add_argument("child_args", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def emit(payload: dict[str, Any], *, as_json: bool) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True)
    print(text)


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "list":
        items = list_setups()
        profiles = list_profiles()
        emit(
            {
                "setups": [item["id"] for item in items],
                "profiles": [item["id"] for item in profiles],
                "default_setup": DEFAULT_SETUP_ID,
                "default_profile": DEFAULT_PROFILE_ID,
                "items": items,
                "profile_items": profiles,
                "legacy_setups": list(LEGACY_SETUP_ORDER),
            },
            as_json=args.json,
        )
        return 0
    if args.command == "status":
        emit(status_payload(require_absolute_target(args.target)), as_json=args.json)
        return 0
    if args.command == "software-status":
        emit(software_status(require_absolute_target(args.target)), as_json=args.json)
        return 0
    if args.command == "plan":
        target = require_absolute_target(args.target)
        emit(
            plan_payload(target, load_setup(args.setup), load_profile(args.profile)),
            as_json=args.json,
        )
        return 0
    if args.command == "install":
        target = require_absolute_target(args.target)
        emit(
            write_setup(target, load_setup(args.setup), load_profile(args.profile)),
            as_json=args.json,
        )
        return 0
    if args.command == "switch":
        target = require_absolute_target(args.target)
        emit(
            write_setup(
                target,
                load_setup(args.setup),
                load_profile(args.profile),
                require_existing=True,
            ),
            as_json=args.json,
        )
        return 0
    if args.command == "migrate":
        target = require_absolute_target(args.target)
        emit(migrate_setup(target, load_setup(args.setup), args.profile), as_json=args.json)
        return 0
    if args.command == "restore":
        target = require_absolute_target(args.target)
        emit(restore_backup(target, args.backup), as_json=args.json)
        return 0
    if args.command == "remove":
        target = require_absolute_target(args.target)
        emit(remove_setup(target), as_json=args.json)
        return 0
    if args.command in {"install-cli", "update-cli"}:
        target = require_absolute_target(args.target)
        emit(install_grok_software(target, args.command), as_json=args.json)
        return 0
    if args.command == "remove-cli":
        target = require_absolute_target(args.target)
        emit(remove_grok_software(target), as_json=args.json)
        return 0
    if args.command == "launch":
        child_args = list(args.child_args)
        if child_args[:1] == ["--"]:
            child_args = child_args[1:]
        return launch(require_absolute_target(args.target), child_args)
    fail(f"unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return dispatch(args)
    except GrokBuildSetupError as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
