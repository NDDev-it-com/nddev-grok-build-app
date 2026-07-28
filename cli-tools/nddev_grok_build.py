#!/usr/bin/env python3
"""Transactional setup manager for an explicit Grok Build home."""

from __future__ import annotations

import argparse
import base64
import binascii
import contextlib
import ctypes
import errno
import fcntl
import hashlib
import http.client
import json
import os
import platform
import re
import shutil
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
PRODUCT_LOCK_FILE_NAME = "global.lock"
PRODUCT_LOCK_NAMESPACE = f"{PRODUCT_NAME}:product-lock:v1"
TARGET_LOCK_ROOT_NAME = "target-locks"
TARGET_LOCK_SUFFIX = ".lock"
TARGET_LOCK_NAMESPACE = f"{PRODUCT_NAME}:target-lock:v1"
BOOTSTRAP_LOCK_NAMESPACE = TARGET_LOCK_NAMESPACE
MANAGED_MAX_BYTES = 8 * 1024 * 1024
METADATA_MAX_BYTES = 256 * 1024
SOFTWARE_MAX_BYTES = 256 * 1024 * 1024
READ_LIFECYCLE_MAX_ATTEMPTS = 4
ANCHOR_STAGE_MAX_ALIASES = 8
ANCHOR_STAGE_NUMBER_MAX_DIGITS = 20
ANCHOR_NAMESPACE_MAX_ENTRIES = 4096
AT_FDCWD_BY_SYSTEM = {"darwin": -2, "linux": -100}
RENAME_EXCL_DARWIN = 0x00000004
RENAME_NOREPLACE_LINUX = 1
RENAMEAT2_SYSCALL_BY_MACHINE = {
    "amd64": 316,
    "x86_64": 316,
    "aarch64": 276,
    "arm64": 276,
}
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
MERGED_MARKER_PATHS = {"config.toml", "AGENTS.md"}
SETUP_ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
SUPPORTED_PLATFORM_SYSTEMS = {"Darwin", "Linux"}
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
FORBIDDEN_MANAGED_PATH_ROOTS = {
    CONTROL_DIR_NAME,
    ".nddev-grok-build-runtime",
    ".nddev-software",
}


class GrokBuildSetupError(Exception):
    """Safe user-facing lifecycle failure."""


class ReadLifecycleRetry(Exception):
    """Cold read saw bootstrap namespace movement and must recompute."""


class ProductLockHandle(NamedTuple):
    descriptor: int
    path: Path
    product_root: Path
    system_root: Path
    mode: int
    product_root_snapshot: DirectoryMetadata | None


class ExternalTargetLockHandle(NamedTuple):
    descriptor: int
    path: Path
    canonical_target: str


class ColdProductNamespaceSnapshot(NamedTuple):
    present: bool
    mode: int | None
    uid: int | None
    gid: int | None
    dev: int | None
    ino: int | None
    nlink: int | None
    size: int | None
    mtime_ns: int | None


class DirectoryMetadata(NamedTuple):
    dev: int
    ino: int
    mode: int
    uid: int
    gid: int
    nlink: int
    size: int
    atime_ns: int
    mtime_ns: int


class AnchorStageAlias(NamedTuple):
    path: Path
    dev: int
    ino: int
    mode: int
    uid: int
    gid: int
    nlink: int
    size: int
    mtime_ns: int


class BootstrapProductRootSetup(NamedTuple):
    system_root: Path
    product_root: Path
    created: bool
    system_snapshot: DirectoryMetadata
    product_snapshot: DirectoryMetadata | None


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


def lexical_target_identity(target: Path) -> str:
    if not target.is_absolute():
        fail("target must be an absolute path")
    normalized = Path(os.path.normpath(str(target)))
    if not normalized.is_absolute():
        fail("target must be an absolute path")
    if normalized.name in ("", ".", ".."):
        fail("target must name a directory")
    return str(normalized)


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
        with contextlib.suppress(FileNotFoundError, OSError):
            path.rmdir()


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


def product_anchor_path(product_root: Path) -> Path:
    return product_root / PRODUCT_LOCK_FILE_NAME


def target_lock_root_path(product_root: Path) -> Path:
    return product_root / TARGET_LOCK_ROOT_NAME


def bootstrap_target_identity(target: Path) -> str:
    return canonical_target_identity(validate_target(target, create=False))


def canonical_target_identity(target: Path) -> str:
    return str(target)


def bootstrap_lock_digest(identity: str) -> str:
    payload = f"{BOOTSTRAP_LOCK_NAMESPACE}\n{identity}\n".encode("utf-8")
    return sha256_bytes(payload)


def bootstrap_lock_path_for_root(product_root: Path, identity: str) -> Path:
    return (
        target_lock_root_path(product_root)
        / f"{bootstrap_lock_digest(identity)}{TARGET_LOCK_SUFFIX}"
    )


def bootstrap_lock_path(identity: str) -> Path:
    product_root = bootstrap_product_root_path(bootstrap_system_root())
    return bootstrap_lock_path_for_root(product_root, identity)


def product_lock_binding() -> dict[str, Any]:
    return {
        "schema_version": BOOTSTRAP_LOCK_SCHEMA_VERSION,
        "product_name": PRODUCT_NAME,
        "namespace": PRODUCT_LOCK_NAMESPACE,
        "anchor": PRODUCT_LOCK_FILE_NAME,
    }


def bootstrap_lock_binding(identity: str) -> dict[str, Any]:
    return {
        "schema_version": BOOTSTRAP_LOCK_SCHEMA_VERSION,
        "product_name": PRODUCT_NAME,
        "namespace": BOOTSTRAP_LOCK_NAMESPACE,
        "canonical_target": identity,
        "lock_id": bootstrap_lock_digest(identity),
    }


def validate_product_lock_binding(value: Any) -> None:
    if not isinstance(value, dict):
        fail("product lock binding must contain a JSON object")
    expected = product_lock_binding()
    if set(value) != set(expected):
        fail("product lock binding has invalid keys")
    if value != expected:
        fail("product lock binding does not match the product")


def validate_bootstrap_lock_binding(value: Any, identity: str) -> None:
    if not isinstance(value, dict):
        fail("target lock binding must contain a JSON object")
    expected = bootstrap_lock_binding(identity)
    if set(value) != set(expected):
        fail("target lock binding has invalid keys")
    if value != expected:
        fail("target lock binding does not match the target")


def expected_product_lock_binding_bytes() -> bytes:
    data = canonical_json(product_lock_binding())
    if len(data) > METADATA_MAX_BYTES:
        fail("product lock binding is too large")
    return data


def expected_bootstrap_lock_binding_bytes(identity: str) -> bytes:
    data = canonical_json(bootstrap_lock_binding(identity))
    if len(data) > METADATA_MAX_BYTES:
        fail("target lock binding is too large")
    return data


def read_lock_binding(descriptor: int, *, label: str) -> bytes:
    size = os.fstat(descriptor).st_size
    if size == 0:
        fail(f"{label} binding is missing")
    if size > METADATA_MAX_BYTES:
        fail(f"{label} binding is too large")
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(descriptor, 65536)
        if not chunk:
            break
        total += len(chunk)
        if total > METADATA_MAX_BYTES:
            fail(f"{label} binding is too large")
        chunks.append(chunk)
    return b"".join(chunks)


def read_product_lock_binding(descriptor: int) -> bytes:
    data = read_lock_binding(descriptor, label="product lock")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"product lock binding is invalid JSON: {exc}")
    validate_product_lock_binding(value)
    if data != expected_product_lock_binding_bytes():
        fail("product lock binding is not canonical")
    return data


def read_bootstrap_lock_binding(descriptor: int, identity: str) -> bytes:
    data = read_lock_binding(descriptor, label="target lock")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"target lock binding is invalid JSON: {exc}")
    validate_bootstrap_lock_binding(value, identity)
    if data != expected_bootstrap_lock_binding_bytes(identity):
        fail("target lock binding is not canonical")
    return data


def fsync_directory(path: Path, label: str) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        fail(f"{label} sync failed: {exc}")
    try:
        os.fsync(descriptor)
    except OSError as exc:
        fail(f"{label} sync failed: {exc}")
    finally:
        os.close(descriptor)


def restore_directory_mtime(path: Path, mtime_ns: int, label: str) -> None:
    try:
        current = path.lstat()
        os.utime(path, ns=(int(current.st_atime_ns), mtime_ns), follow_symlinks=False)
    except PermissionError:
        return
    except OSError as exc:
        fail(f"{label} mtime restore failed: {exc}")
    if stat.S_ISDIR(current.st_mode):
        fsync_directory(path, f"{label} mtime restore")


def directory_metadata(path: Path, label: str) -> DirectoryMetadata:
    info = require_private_directory(path, label)
    return DirectoryMetadata(
        dev=int(info.st_dev),
        ino=int(info.st_ino),
        mode=stat.S_IMODE(info.st_mode),
        uid=int(info.st_uid),
        gid=int(info.st_gid),
        nlink=int(info.st_nlink),
        size=int(info.st_size),
        atime_ns=int(info.st_atime_ns),
        mtime_ns=int(info.st_mtime_ns),
    )


def observed_directory_metadata(path: Path, label: str) -> DirectoryMetadata:
    try:
        info = path.lstat()
    except OSError as exc:
        fail(f"{label} cannot be inspected: {exc}")
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    return DirectoryMetadata(
        dev=int(info.st_dev),
        ino=int(info.st_ino),
        mode=stat.S_IMODE(info.st_mode),
        uid=int(info.st_uid),
        gid=int(info.st_gid),
        nlink=int(info.st_nlink),
        size=int(info.st_size),
        atime_ns=int(info.st_atime_ns),
        mtime_ns=int(info.st_mtime_ns),
    )


def restore_directory_metadata(
    path: Path, snapshot: DirectoryMetadata, label: str, *, verify_topology: bool = True
) -> None:
    current = require_private_directory(path, label)
    if (current.st_dev, current.st_ino) != (snapshot.dev, snapshot.ino):
        fail(f"{label} identity changed during recovery")
    if (current.st_uid, current.st_gid) != (snapshot.uid, snapshot.gid):
        fail(f"{label} owner changed during recovery")
    if verify_topology and (current.st_nlink, current.st_size) != (
        snapshot.nlink,
        snapshot.size,
    ):
        fail(f"{label} topology changed during recovery")
    if stat.S_IMODE(current.st_mode) != snapshot.mode:
        path.chmod(snapshot.mode)
    os.utime(path, ns=(snapshot.atime_ns, snapshot.mtime_ns), follow_symlinks=False)
    fsync_directory(path, f"{label} metadata restore")
    final = require_private_directory(path, label)
    if (final.st_dev, final.st_ino) != (snapshot.dev, snapshot.ino):
        fail(f"{label} identity changed after recovery")
    if (final.st_uid, final.st_gid) != (snapshot.uid, snapshot.gid):
        fail(f"{label} owner changed after recovery")
    if verify_topology and (final.st_nlink, final.st_size) != (snapshot.nlink, snapshot.size):
        fail(f"{label} topology changed after recovery")
    if stat.S_IMODE(final.st_mode) != snapshot.mode:
        fail(f"{label} mode changed after recovery")
    if int(final.st_atime_ns) != snapshot.atime_ns or int(final.st_mtime_ns) != snapshot.mtime_ns:
        fail(f"{label} timestamp changed after recovery")


def restore_observed_directory_metadata(
    path: Path, snapshot: DirectoryMetadata, label: str
) -> None:
    current = observed_directory_metadata(path, label)
    if (current.dev, current.ino) != (snapshot.dev, snapshot.ino):
        fail(f"{label} identity changed during recovery")
    if (current.uid, current.gid) != (snapshot.uid, snapshot.gid):
        fail(f"{label} owner changed during recovery")
    if (current.nlink, current.size) != (snapshot.nlink, snapshot.size):
        fail(f"{label} topology changed during recovery")
    if current.mode != snapshot.mode:
        fail(f"{label} mode changed during recovery")
    os.utime(path, ns=(snapshot.atime_ns, snapshot.mtime_ns), follow_symlinks=False)
    fsync_directory(path, f"{label} metadata restore")
    final = observed_directory_metadata(path, label)
    if (final.dev, final.ino) != (snapshot.dev, snapshot.ino):
        fail(f"{label} identity changed after recovery")
    if (final.uid, final.gid) != (snapshot.uid, snapshot.gid):
        fail(f"{label} owner changed after recovery")
    if (final.nlink, final.size) != (snapshot.nlink, snapshot.size):
        fail(f"{label} topology changed after recovery")
    if final.mode != snapshot.mode:
        fail(f"{label} mode changed after recovery")
    if final.atime_ns != snapshot.atime_ns or final.mtime_ns != snapshot.mtime_ns:
        fail(f"{label} timestamp changed after recovery")


def require_anchor_file_stat(info: os.stat_result, label: str) -> None:
    if not stat.S_ISREG(info.st_mode):
        fail(f"{label} must be a regular file")
    require_current_user_owner(info, label)
    if info.st_nlink != 1:
        fail(f"{label} must not be a hardlink")
    if stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
        fail(f"{label} must have mode 0600")
    if info.st_size == 0:
        fail(f"{label} binding is missing")
    if info.st_size > METADATA_MAX_BYTES:
        fail(f"{label} binding is too large")


def anchor_stage_alias_from_stat(path: Path, info: os.stat_result) -> AnchorStageAlias:
    return AnchorStageAlias(
        path=path,
        dev=int(info.st_dev),
        ino=int(info.st_ino),
        mode=stat.S_IMODE(info.st_mode),
        uid=int(info.st_uid),
        gid=int(info.st_gid),
        nlink=int(info.st_nlink),
        size=int(info.st_size),
        mtime_ns=int(info.st_mtime_ns),
    )


def require_anchor_stage_alias_matches(
    info: os.stat_result, expected: AnchorStageAlias, label: str
) -> None:
    require_anchor_file_stat(info, label)
    actual = anchor_stage_alias_from_stat(expected.path, info)
    if actual != expected:
        fail(f"{label} changed before cleanup")


def validated_staged_lock_file(path: Path, data: bytes, label: str) -> AnchorStageAlias:
    before = stat_existing(path, label)
    if before is None:
        fail(f"{label} disappeared while staging")
    require_anchor_file_stat(before, label)
    expected = anchor_stage_alias_from_stat(path, before)
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        fail(f"{label} could not be opened safely: {exc}")
    try:
        opened = os.fstat(descriptor)
        require_anchor_stage_alias_matches(opened, expected, label)
        os.lseek(descriptor, 0, os.SEEK_SET)
        payload = os.read(descriptor, METADATA_MAX_BYTES + 1)
        if payload != data:
            fail(f"{label} staged binding postcondition failed")
    finally:
        os.close(descriptor)
    current = stat_existing(path, label)
    if current is None:
        fail(f"{label} changed after staging")
    require_anchor_stage_alias_matches(current, expected, label)
    return expected


def verify_staged_lock_file(path: Path, data: bytes, label: str) -> None:
    validated_staged_lock_file(path, data, label)


def write_lock_stage_file(path: Path, data: bytes, label: str) -> AnchorStageAlias:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, OWNER_FILE_MODE)
    try:
        offset = 0
        while offset < len(data):
            written = os.write(descriptor, data[offset:])
            if written <= 0:
                fail(f"{label} binding write made no progress")
            offset += written
        os.fchmod(descriptor, OWNER_FILE_MODE)
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        with contextlib.suppress(FileNotFoundError, OSError):
            path.unlink()
        raise
    os.close(descriptor)
    return validated_staged_lock_file(path, data, label)


def cleanup_lock_stage_file(path: Path, label: str) -> None:
    info = stat_existing(path, label)
    if info is None:
        return
    require_anchor_file_stat(info, label)
    try:
        path.unlink()
    except OSError as exc:
        fail(f"{label} cleanup failed: {exc}")
    fsync_directory(path.parent, f"{label} cleanup")


def cleanup_validated_anchor_stage_alias(alias: AnchorStageAlias, data: bytes, label: str) -> None:
    revalidated = validated_staged_lock_file(alias.path, data, label)
    if revalidated != alias:
        fail(f"{label} changed before cleanup")
    try:
        alias.path.unlink()
    except OSError as exc:
        fail(f"{label} cleanup failed: {exc}")
    fsync_directory(alias.path.parent, f"{label} cleanup")


def bounded_directory_entries(path: Path, label: str) -> list[Path]:
    entries: list[Path] = []
    try:
        iterator = path.iterdir()
        for entry in iterator:
            if len(entries) >= ANCHOR_NAMESPACE_MAX_ENTRIES:
                fail(f"{label} contains too many entries")
            entries.append(entry)
    except FileNotFoundError:
        raise ReadLifecycleRetry
    except OSError as exc:
        fail(f"{label} cannot be inspected: {exc}")
    return sorted(entries, key=lambda item: item.name)


def anchor_stage_prefix(path: Path) -> str:
    return f".{path.name}.nddev.tmp."


def anchor_stage_name_is_exact(path: Path, name: str) -> bool:
    prefix = anchor_stage_prefix(path)
    if not name.startswith(prefix):
        return False
    suffix = name[len(prefix) :]
    parts = suffix.split(".")
    if len(parts) != 2:
        return False
    for part in parts:
        if not part.isdecimal():
            return False
        if not (1 <= len(part) <= ANCHOR_STAGE_NUMBER_MAX_DIGITS):
            return False
    return True


def validated_anchor_stage_aliases(path: Path, data: bytes, label: str) -> list[AnchorStageAlias]:
    aliases: list[Path] = []
    prefix = anchor_stage_prefix(path)
    for candidate in bounded_directory_entries(path.parent, f"{label} parent"):
        if not candidate.name.startswith(prefix):
            continue
        if not anchor_stage_name_is_exact(path, candidate.name):
            fail(f"{label} has malformed publication stage")
        aliases.append(candidate)
    if len(aliases) > ANCHOR_STAGE_MAX_ALIASES:
        fail(f"{label} has excessive publication stages")
    return [validated_staged_lock_file(alias, data, f"{label} staged binding") for alias in aliases]


def final_anchor_matches(path: Path, data: bytes, label: str) -> bool:
    try:
        validated_staged_lock_file(path, data, label)
    except GrokBuildSetupError:
        return False
    return True


def publish_validated_anchor_stage(
    path: Path, stage: AnchorStageAlias, data: bytes, label: str
) -> bool:
    try:
        published = rename_no_replace(stage.path, path, label)
    except FileNotFoundError:
        if final_anchor_matches(path, data, label):
            return False
        fail(f"{label} publication stage disappeared without a valid final anchor")
    if not published:
        return False
    fsync_directory(path.parent, f"{label} recovered publication")
    return True


def drain_anchor_stage_aliases(path: Path, data: bytes, label: str) -> None:
    parent_snapshot = directory_metadata(path.parent, f"{label} parent")
    aliases = validated_anchor_stage_aliases(path, data, label)
    for alias in aliases:
        cleanup_validated_anchor_stage_alias(alias, data, f"{label} staged binding")
    if aliases:
        restore_directory_metadata(
            path.parent, parent_snapshot, f"{label} parent", verify_topology=False
        )


def fail_if_anchor_stage_aliases_exist(path: Path, data: bytes, label: str) -> None:
    aliases = validated_anchor_stage_aliases(path, data, label)
    if aliases:
        fail(f"{label} has pending publication stages")


def target_lock_final_name_is_valid(name: str) -> bool:
    return (
        name.endswith(TARGET_LOCK_SUFFIX)
        and SHA256_PATTERN.fullmatch(name[: -len(TARGET_LOCK_SUFFIX)]) is not None
    )


def target_lock_stage_name_is_valid(name: str) -> bool:
    if not name.startswith(".") or ".nddev.tmp." not in name:
        return False
    final_name, suffix = name[1:].split(".nddev.tmp.", 1)
    if not target_lock_final_name_is_valid(final_name):
        return False
    parts = suffix.split(".")
    if len(parts) != 2:
        return False
    return all(
        part.isdecimal() and 1 <= len(part) <= ANCHOR_STAGE_NUMBER_MAX_DIGITS for part in parts
    )


def validate_target_lock_root_entries(root: Path, *, allow_stage_aliases: bool) -> None:
    for entry in bounded_directory_entries(root, "target lock root"):
        if target_lock_final_name_is_valid(entry.name):
            validate_target_lock_entry(entry)
            continue
        if target_lock_stage_name_is_valid(entry.name):
            if allow_stage_aliases:
                continue
            fail("target lock root contains pending publication stages")
        fail(f"target lock root contains unknown entry: {entry.name}")


def rename_no_replace(source: Path, destination: Path, label: str) -> bool:
    system = platform.system().lower()
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    if system == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        renameatx_np = libc.renameatx_np
        renameatx_np.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameatx_np.restype = ctypes.c_int
        result = renameatx_np(
            AT_FDCWD_BY_SYSTEM["darwin"],
            source_bytes,
            AT_FDCWD_BY_SYSTEM["darwin"],
            destination_bytes,
            RENAME_EXCL_DARWIN,
        )
    elif system == "linux":
        machine = platform.machine().lower()
        syscall_number = RENAMEAT2_SYSCALL_BY_MACHINE.get(machine)
        if syscall_number is None:
            fail(f"{label} no-replace publication is unsupported on this architecture")
        libc = ctypes.CDLL(None, use_errno=True)
        syscall = libc.syscall
        syscall.restype = ctypes.c_long
        result = syscall(
            ctypes.c_long(syscall_number),
            ctypes.c_int(AT_FDCWD_BY_SYSTEM["linux"]),
            ctypes.c_char_p(source_bytes),
            ctypes.c_int(AT_FDCWD_BY_SYSTEM["linux"]),
            ctypes.c_char_p(destination_bytes),
            ctypes.c_uint(RENAME_NOREPLACE_LINUX),
        )
    else:
        fail(f"{label} no-replace publication is unsupported on this platform")
    if result == 0:
        return True
    error = ctypes.get_errno()
    if error == errno.EEXIST:
        return False
    if error == errno.ENOENT:
        raise FileNotFoundError(errno.ENOENT, os.strerror(error), str(source))
    if error in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}:
        fail(f"{label} no-replace publication primitive is unavailable")
    fail(f"{label} no-replace publication failed: {os.strerror(error)}")


def write_atomic_anchor(path: Path, data: bytes, mode: int, label: str) -> bool:
    parent = path.parent
    parent_snapshot = directory_metadata(parent, f"{label} parent")
    stage = path.with_name(f".{path.name}.nddev.tmp.{os.getpid()}.{time.time_ns()}")
    stage_alias: AnchorStageAlias | None = None
    published = False
    try:
        stage_alias = write_lock_stage_file(stage, data, f"{label} staged binding")
        if not rename_no_replace(stage, path, label):
            if final_anchor_matches(path, data, label):
                return False
            cleanup_validated_anchor_stage_alias(stage_alias, data, f"{label} staged binding")
            restore_directory_metadata(parent, parent_snapshot, f"{label} parent")
            fail(f"{label} existing final anchor is invalid")
        published = True
        fsync_directory(parent, f"{label} publication")
        return True
    except BaseException:
        if path.exists() or path.is_symlink():
            current = stat_existing(path, label)
            if current is not None and stat.S_ISREG(current.st_mode):
                published = True
        if stage.exists() or stage.is_symlink():
            if stage_alias is None:
                fail(f"{label} staged binding lacks cleanup authority")
            cleanup_validated_anchor_stage_alias(stage_alias, data, f"{label} staged binding")
        if not published:
            restore_directory_metadata(parent, parent_snapshot, f"{label} parent")
        raise


def ensure_bootstrap_product_root_for_publication() -> BootstrapProductRootSetup:
    system_root = bootstrap_system_root()
    product_root = bootstrap_product_root_path(system_root)
    system_snapshot = observed_directory_metadata(system_root, "bootstrap system root")
    info = stat_existing(product_root, "product lock root")
    created = False
    if info is None:
        try:
            product_root.mkdir(mode=OWNER_DIRECTORY_MODE)
            created = True
            product_root.chmod(OWNER_DIRECTORY_MODE)
            fsync_directory(system_root, "product lock root creation")
        except FileExistsError:
            pass
        except BaseException:
            if created:
                entries = bounded_directory_entries(product_root, "product lock root rollback")
                if entries:
                    fail("product lock root rollback found unexpected entries")
                try:
                    product_root.rmdir()
                except OSError as exc:
                    fail(f"product lock root rollback failed: {exc}")
                fsync_directory(system_root, "product lock root rollback")
                restore_observed_directory_metadata(
                    system_root, system_snapshot, "bootstrap system root"
                )
            raise
    require_private_directory(product_root, "product lock root")
    product_snapshot = None if created else directory_metadata(product_root, "product lock root")
    return BootstrapProductRootSetup(
        system_root=system_root,
        product_root=product_root,
        created=created,
        system_snapshot=system_snapshot,
        product_snapshot=product_snapshot,
    )


def ensure_bootstrap_product_root() -> Path:
    return ensure_bootstrap_product_root_for_publication().product_root


def rollback_bootstrap_product_root_publication(
    setup: BootstrapProductRootSetup, final_anchor: Path
) -> None:
    if final_anchor.exists() or final_anchor.is_symlink():
        return
    if setup.created:
        entries = bounded_directory_entries(setup.product_root, "product lock root rollback")
        if entries:
            fail("product lock root rollback found unexpected entries")
        try:
            setup.product_root.rmdir()
        except OSError as exc:
            fail(f"product lock root rollback failed: {exc}")
        fsync_directory(setup.system_root, "product lock root rollback")
        restore_observed_directory_metadata(
            setup.system_root, setup.system_snapshot, "bootstrap system root"
        )
        return
    if setup.product_snapshot is not None:
        restore_directory_metadata(setup.product_root, setup.product_snapshot, "product lock root")


def product_root_namespace_entries(product_root: Path) -> list[Path]:
    return bounded_directory_entries(product_root, "product lock namespace")


def require_empty_product_namespace_without_anchor(product_root: Path) -> None:
    entries = product_root_namespace_entries(product_root)
    if not entries:
        return
    names = ", ".join(entry.name for entry in entries[:4])
    fail(f"product lock namespace must be empty without product anchor: {names}")


def product_anchor_stages_for_publication(product_root: Path) -> list[AnchorStageAlias]:
    path = product_anchor_path(product_root)
    data = expected_product_lock_binding_bytes()
    aliases = validated_anchor_stage_aliases(path, data, "product lock")
    alias_names = {alias.path.name for alias in aliases}
    unknown = [
        entry.name
        for entry in product_root_namespace_entries(product_root)
        if entry.name not in alias_names
    ]
    if unknown:
        fail(f"product lock namespace contains unknown entries: {', '.join(unknown[:4])}")
    return aliases


def validate_product_namespace_entries(
    product_root: Path, *, allow_target_stage_aliases: bool
) -> None:
    entries = product_root_namespace_entries(product_root)
    allowed = {PRODUCT_LOCK_FILE_NAME, TARGET_LOCK_ROOT_NAME}
    unknown = sorted(entry.name for entry in entries if entry.name not in allowed)
    if unknown:
        fail(f"product lock namespace contains unknown entries: {', '.join(unknown[:4])}")
    if (
        target_lock_root_path(product_root).exists()
        or target_lock_root_path(product_root).is_symlink()
    ):
        require_private_directory(target_lock_root_path(product_root), "target lock root")
        validate_target_lock_root_entries(
            target_lock_root_path(product_root),
            allow_stage_aliases=allow_target_stage_aliases,
        )


def publish_product_anchor_if_missing(product_root: Path) -> bool:
    path = product_anchor_path(product_root)
    if path.exists() or path.is_symlink():
        return False
    data = expected_product_lock_binding_bytes()
    aliases = product_anchor_stages_for_publication(product_root)
    if aliases:
        created = publish_validated_anchor_stage(path, aliases[0], data, "product lock")
    else:
        require_empty_product_namespace_without_anchor(product_root)
        created = write_atomic_anchor(path, data, OWNER_FILE_MODE, "product lock")
    if created:
        require_existing_managed_file(
            path, "product lock", max_bytes=METADATA_MAX_BYTES, expected_mode=OWNER_FILE_MODE
        )
    return created


def publish_target_anchor_if_missing(product_root: Path, identity: str) -> Path:
    root = target_lock_root_path(product_root)
    root_preexisting = root.exists() or root.is_symlink()
    product_root_snapshot = directory_metadata(product_root, "product lock root")
    root_snapshot = directory_metadata(root, "target lock root") if root_preexisting else None
    if not root_preexisting:
        try:
            root.mkdir(mode=OWNER_DIRECTORY_MODE)
            root.chmod(OWNER_DIRECTORY_MODE)
            fsync_directory(product_root, "target lock root creation")
        except BaseException:
            if root.exists() or root.is_symlink():
                entries = bounded_directory_entries(root, "target lock root rollback")
                if entries:
                    fail("target lock root rollback found unexpected entries")
                try:
                    root.rmdir()
                except OSError as exc:
                    fail(f"target lock root rollback failed: {exc}")
                fsync_directory(product_root, "target lock root rollback")
            restore_directory_metadata(product_root, product_root_snapshot, "product lock root")
            raise
    require_private_directory(root, "target lock root")
    path = bootstrap_lock_path_for_root(product_root, identity)
    if not (path.exists() or path.is_symlink()):
        try:
            data = expected_bootstrap_lock_binding_bytes(identity)
            aliases = validated_anchor_stage_aliases(path, data, "target lock")
            if aliases:
                publish_validated_anchor_stage(path, aliases[0], data, "target lock")
            else:
                write_atomic_anchor(path, data, OWNER_FILE_MODE, "target lock")
        except BaseException:
            if not (path.exists() or path.is_symlink()) and not root_preexisting:
                entries = bounded_directory_entries(root, "target lock root rollback")
                if entries:
                    fail("target lock root rollback found unexpected entries")
                try:
                    root.rmdir()
                except OSError as exc:
                    fail(f"target lock root rollback failed: {exc}")
                fsync_directory(product_root, "target lock root rollback")
                restore_directory_metadata(product_root, product_root_snapshot, "product lock root")
            elif not (path.exists() or path.is_symlink()) and root_snapshot is not None:
                restore_directory_metadata(root, root_snapshot, "target lock root")
                restore_directory_metadata(product_root, product_root_snapshot, "product lock root")
            raise
    return path


def require_product_lock_descriptor(descriptor: int, path: Path) -> os.stat_result:
    opened = os.fstat(descriptor)
    require_anchor_file_stat(opened, "product lock")
    current = stat_existing(path, "product lock")
    if current is None:
        fail("product lock disappeared while opening")
    require_anchor_file_stat(current, "product lock")
    if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
        fail("product lock changed while opening")
    read_product_lock_binding(descriptor)
    return opened


def require_bootstrap_lock_descriptor(descriptor: int, path: Path) -> os.stat_result:
    opened = os.fstat(descriptor)
    require_anchor_file_stat(opened, "target lock")
    current = stat_existing(path, "target lock")
    if current is None:
        fail("target lock disappeared while opening")
    require_anchor_file_stat(current, "target lock")
    if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
        fail("target lock changed while opening")
    return opened


def require_bootstrap_lock_descriptor_for_identity(
    descriptor: int, path: Path, identity: str
) -> os.stat_result:
    opened = require_bootstrap_lock_descriptor(descriptor, path)
    read_bootstrap_lock_binding(descriptor, identity)
    return opened


def validate_target_lock_entry(path: Path) -> None:
    expected_lock_id = path.name[: -len(TARGET_LOCK_SUFFIX)]
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        fail(f"target lock must be a regular owner-private file: {exc}")
    try:
        require_bootstrap_lock_descriptor(descriptor, path)
        data = read_lock_binding(descriptor, label="target lock")
        try:
            value = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            fail(f"target lock binding is invalid JSON: {exc}")
        if not isinstance(value, dict):
            fail("target lock binding must contain a JSON object")
        target = value.get("canonical_target")
        if not isinstance(target, str) or not target.startswith("/"):
            fail("target lock binding canonical target is invalid")
        validate_bootstrap_lock_binding(value, target)
        if value.get("lock_id") != expected_lock_id:
            fail("target lock binding does not match the lock filename")
        if data != expected_bootstrap_lock_binding_bytes(target):
            fail("target lock binding is not canonical")
    finally:
        os.close(descriptor)


def acquire_product_lock(*, create: bool, exclusive: bool) -> ProductLockHandle | None:
    system_root = bootstrap_system_root()
    product_root = bootstrap_product_root_path(system_root)
    product_root_snapshot_for_restore: DirectoryMetadata | None = None
    if create:
        setup = ensure_bootstrap_product_root_for_publication()
        system_root = setup.system_root
        product_root = setup.product_root
        product_anchor = product_anchor_path(product_root)
        product_anchor_preexisting = product_anchor.exists() or product_anchor.is_symlink()
        if product_anchor_preexisting and setup.product_snapshot is not None:
            product_root_snapshot_for_restore = setup.product_snapshot
        try:
            if not (product_anchor.exists() or product_anchor.is_symlink()):
                publish_product_anchor_if_missing(product_root)
        except BaseException:
            rollback_bootstrap_product_root_publication(setup, product_anchor)
            raise
    else:
        if not (product_root.exists() or product_root.is_symlink()):
            return None
        require_private_directory(product_root, "product lock root")
    path = product_anchor_path(product_root)
    if not (path.exists() or path.is_symlink()):
        return None
    flags = os.O_RDWR if exclusive else os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        fail(f"product lock must be a regular owner-private file: {exc}")
    try:
        require_product_lock_descriptor(descriptor, path)
        lock_mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(descriptor, lock_mode)
        require_product_lock_descriptor(descriptor, path)
        if exclusive:
            product_data = expected_product_lock_binding_bytes()
            if validated_anchor_stage_aliases(path, product_data, "product lock"):
                product_root_snapshot_for_restore = None
            drain_anchor_stage_aliases(path, product_data, "product lock")
            require_product_lock_descriptor(descriptor, path)
        else:
            fail_if_anchor_stage_aliases_exist(
                path, expected_product_lock_binding_bytes(), "product lock"
            )
        validate_product_namespace_entries(product_root, allow_target_stage_aliases=exclusive)
        return ProductLockHandle(
            descriptor=descriptor,
            path=path,
            product_root=product_root,
            system_root=system_root,
            mode=lock_mode,
            product_root_snapshot=product_root_snapshot_for_restore,
        )
    except BaseException:
        with contextlib.suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
        raise


def release_product_lock(handle: ProductLockHandle | None) -> None:
    if handle is None:
        return
    with contextlib.suppress(OSError):
        fcntl.flock(handle.descriptor, fcntl.LOCK_UN)
    os.close(handle.descriptor)


def open_external_target_lock(
    product_root: Path,
    identity: str,
    *,
    exclusive: bool,
    create: bool,
    blocking: bool = False,
) -> ExternalTargetLockHandle | None:
    if create:
        path = publish_target_anchor_if_missing(product_root, identity)
    else:
        path = bootstrap_lock_path_for_root(product_root, identity)
        if not (path.exists() or path.is_symlink()):
            fail_if_anchor_stage_aliases_exist(
                path, expected_bootstrap_lock_binding_bytes(identity), "target lock"
            )
            return None
    flags = os.O_RDWR if exclusive else os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        fail(f"target lock must be a regular owner-private file: {exc}")
    try:
        require_bootstrap_lock_descriptor_for_identity(descriptor, path, identity)
        lock_mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        if not blocking:
            lock_mode |= fcntl.LOCK_NB
        try:
            fcntl.flock(descriptor, lock_mode)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}:
                fail(f"target is locked: {path}")
            fail(f"target lock failed: {exc}")
        if exclusive:
            drain_anchor_stage_aliases(
                path, expected_bootstrap_lock_binding_bytes(identity), "target lock"
            )
            require_bootstrap_lock_descriptor_for_identity(descriptor, path, identity)
        else:
            fail_if_anchor_stage_aliases_exist(
                path, expected_bootstrap_lock_binding_bytes(identity), "target lock"
            )
        validate_target_lock_root_entries(
            target_lock_root_path(product_root),
            allow_stage_aliases=False,
        )
        require_bootstrap_lock_descriptor_for_identity(descriptor, path, identity)
        return ExternalTargetLockHandle(
            descriptor=descriptor,
            path=path,
            canonical_target=identity,
        )
    except BaseException:
        with contextlib.suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
        raise


def release_external_target_lock(handle: ExternalTargetLockHandle | None) -> None:
    if handle is None:
        return
    with contextlib.suppress(OSError):
        fcntl.flock(handle.descriptor, fcntl.LOCK_UN)
    os.close(handle.descriptor)


def acquire_bootstrap_lock(target: Path) -> int:
    product = acquire_product_lock(create=True, exclusive=True)
    if product is None:
        fail("product lock was not created")
    target_lock_handle: ExternalTargetLockHandle | None = None
    try:
        canonical = validate_target(target, create=False)
        identity = canonical_target_identity(canonical)
        target_lock_handle = open_external_target_lock(
            product.product_root,
            identity,
            exclusive=True,
            create=True,
            blocking=False,
        )
        if target_lock_handle is None:
            fail("target lock was not created")
        release_product_lock(product)
        product = None
        descriptor = target_lock_handle.descriptor
        target_lock_handle = None
        return descriptor
    except BaseException:
        release_external_target_lock(target_lock_handle)
        if product is not None and product.product_root_snapshot is not None:
            restore_directory_metadata(
                product.product_root, product.product_root_snapshot, "product lock root"
            )
        release_product_lock(product)
        raise


def release_bootstrap_lock(descriptor: int) -> None:
    with contextlib.suppress(OSError):
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    os.close(descriptor)


def cold_product_namespace_snapshot(product_root: Path) -> ColdProductNamespaceSnapshot:
    info = stat_existing(product_root, "product lock root")
    if info is None:
        return ColdProductNamespaceSnapshot(False, None, None, None, None, None, None, None, None)
    if not stat.S_ISDIR(info.st_mode):
        fail("product lock root must be a directory")
    require_current_user_owner(info, "product lock root")
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        fail("product lock root must have mode 0700")
    entries = product_root_namespace_entries(product_root)
    if entries:
        if any(entry.name == PRODUCT_LOCK_FILE_NAME for entry in entries):
            raise ReadLifecycleRetry
        if any(entry.name == TARGET_LOCK_ROOT_NAME for entry in entries):
            fail("target lock namespace exists without product anchor")
        names = ", ".join(entry.name for entry in entries[:4])
        fail(f"product lock namespace must be empty without product anchor: {names}")
    return ColdProductNamespaceSnapshot(
        True,
        stat.S_IMODE(info.st_mode),
        int(info.st_uid),
        int(info.st_gid),
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_nlink),
        int(info.st_size),
        int(info.st_mtime_ns),
    )


@contextlib.contextmanager
def read_lifecycle_coordination(target: Path):
    product = acquire_product_lock(create=False, exclusive=False)
    target_lock_handle: ExternalTargetLockHandle | None = None
    if product is None:
        system_root = bootstrap_system_root()
        product_root = bootstrap_product_root_path(system_root)
        before = cold_product_namespace_snapshot(product_root)
        try:
            canonical = validate_target(target, create=False)
            if cold_product_namespace_snapshot(product_root) != before:
                raise ReadLifecycleRetry
            yield canonical
        except GrokBuildSetupError:
            if cold_product_namespace_snapshot(product_root) != before:
                raise ReadLifecycleRetry
            raise
        after = cold_product_namespace_snapshot(product_root)
        if after != before:
            raise ReadLifecycleRetry
        return
    try:
        canonical = validate_target(target, create=False)
        identity = canonical_target_identity(canonical)
        target_lock_handle = open_external_target_lock(
            product.product_root,
            identity,
            exclusive=False,
            create=False,
            blocking=False,
        )
        if target_lock_handle is not None:
            release_product_lock(product)
            product = None
        yield canonical
        if target_lock_handle is None:
            target_anchor = bootstrap_lock_path_for_root(product.product_root, identity)
            if target_anchor.exists() or target_anchor.is_symlink():
                fail("target lock anchor appeared without coordination")
    finally:
        release_external_target_lock(target_lock_handle)
        release_product_lock(product)


def read_lifecycle_payload(target: Path, reader: Any) -> Any:
    for attempt in range(READ_LIFECYCLE_MAX_ATTEMPTS):
        try:
            with read_lifecycle_coordination(target) as coordinated_target:
                return reader(coordinated_target)
        except ReadLifecycleRetry:
            if attempt + 1 >= READ_LIFECYCLE_MAX_ATTEMPTS:
                fail("read-only lifecycle coordination changed during inspection")
            continue
    fail("read-only lifecycle coordination changed during inspection")


@contextlib.contextmanager
def bootstrap_lifecycle_lock(target: Path):
    with read_lifecycle_coordination(target) as coordinated_target:
        yield coordinated_target


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
            path.rmdir()
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
    path.unlink()


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
        with contextlib.suppress(FileNotFoundError, OSError):
            directory.rmdir()
    path = lock_path(target)
    if path.exists() or path.is_symlink():
        require_existing_managed_file(
            path, "target lock", max_bytes=METADATA_MAX_BYTES, expected_mode=OWNER_FILE_MODE
        )
        path.unlink()
    parent = lock_parent_dir(target)
    if parent.exists() or parent.is_symlink():
        require_lock_parent_directory(parent, "target lock parent", allow_locked=True)
        if stat.S_IMODE(parent.lstat().st_mode) == LOCK_PARENT_HELD_MODE:
            parent.chmod(OWNER_DIRECTORY_MODE)
        with contextlib.suppress(FileNotFoundError, OSError):
            parent.rmdir()
    recover_legacy_lock_state(target)
    with contextlib.suppress(FileNotFoundError, OSError):
        control.rmdir()


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
    bootstrap_descriptor: int | None = None
    descriptor: int | None = None
    locked_parent = False
    restore_error: BaseException | None = None
    try:
        bootstrap_descriptor = acquire_bootstrap_lock(target)
        created_parent_chain = missing_directory_chain(target.parent)
        remove_empty_target = create and not (target.exists() or target.is_symlink())
        target = validate_target(target, create=create)
        if not create and not target.exists() and not target.is_symlink():
            fail("target is missing")
        descriptor = acquire_target_lock(target)
        prepare_locked_lock_parent(target)
        locked_parent = True
        yield target
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
        prune_empty_control_dirs(target)
        if remove_empty_target:
            remove_created_lock_state_if_empty(target)
            remove_empty_directory_if_created(target, existed_before=False)
        remove_created_empty_directories(created_parent_chain)
        if bootstrap_descriptor is not None:
            release_bootstrap_lock(bootstrap_descriptor)
        if restore_error is not None:
            raise restore_error


def prune_empty_control_dirs(target: Path) -> None:
    for directory in (
        launch_image_dir(target),
        control_tmp_dir(target),
        backup_pool(target),
        lock_parent_dir(target),
        managed_control_dir(target),
    ):
        with contextlib.suppress(FileNotFoundError, OSError):
            directory.rmdir()


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


def atomic_write(path: Path, data: bytes, target: Path) -> None:
    ensure_real_parent(path, target)
    require_existing_managed_file(path, str(path), max_bytes=MANAGED_MAX_BYTES)
    temporary = path.with_name(f".{path.name}.nddev.tmp.{os.getpid()}.{time.time_ns()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(temporary, flags, OWNER_FILE_MODE)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(temporary, path)
        path.chmod(OWNER_FILE_MODE)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise


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


def require_supported_runtime_platform() -> None:
    system = platform.system()
    if system not in SUPPORTED_PLATFORM_SYSTEMS:
        fail(f"unsupported platform for nddev-grok-build-app runtime management: {system}")


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
    return read_lifecycle_payload(target, status_payload_locked)


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
) -> dict[str, bytes | None]:
    snapshot: dict[str, bytes | None] = {}
    paths = list(content_managed_paths())
    if extra_paths is not None:
        paths.extend(extra_paths)
    for relative in (*tuple(dict.fromkeys(paths)), STAMP_NAME):
        snapshot[relative] = read_existing_file(
            safe_target_path(target, relative), max_bytes=MANAGED_MAX_BYTES, label=relative
        )
    return snapshot


def restore_snapshot(target: Path, snapshot: dict[str, bytes | None]) -> None:
    for relative, data in snapshot.items():
        path = safe_target_path(target, relative)
        if data is None:
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
            continue
        atomic_write(path, data, target)
    prune_empty_managed_dirs(target)


def choose_backup_slot(pool: Path) -> int:
    require_control_directory(pool.parent, "NDDev control root", allow_locked=False)
    ensure_private_directory(pool, "backup pool")
    for slot in range(10):
        if not (pool / str(slot)).exists():
            return slot
    return min(range(10), key=lambda item: (pool / str(item)).stat().st_mtime_ns)


def create_backup(target: Path, stamp: dict[str, Any]) -> int:
    pool = backup_pool(target)
    slot = choose_backup_slot(pool)
    slot_dir = pool / str(slot)
    if slot_dir.exists():
        require_private_directory(slot_dir, "backup slot")
        shutil.rmtree(slot_dir)
    slot_dir.mkdir(mode=OWNER_DIRECTORY_MODE)
    slot_dir.chmod(OWNER_DIRECTORY_MODE)
    require_private_directory(slot_dir, "backup slot")
    files: dict[str, Any] = {}
    managed_paths = sorted(stamp.get("managed_files", {}))
    for relative in (*managed_paths, STAMP_NAME):
        data = read_existing_file(
            safe_target_path(target, relative), max_bytes=MANAGED_MAX_BYTES, label=relative
        )
        files[relative] = None if data is None else base64.b64encode(data).decode("ascii")
    envelope = {
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
    atomic_write(slot_dir / BACKUP_NAME, canonical_json(envelope), slot_dir)
    return slot


def decode_backup_payload(relative: str, encoded: Any) -> bytes:
    if not isinstance(encoded, str):
        fail(f"backup file payload is invalid: {relative}")
    try:
        data = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError) as exc:
        fail(f"backup file payload is not valid base64: {relative}: {exc}")
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
        if current is None:
            changed = sorted(files)
        else:
            changed = [
                relative
                for relative, data in files.items()
                if current_managed_digest(target, relative)
                != managed_digest_for_bytes(relative, data)
            ]
        backup_slot = None
        if current is not None and (
            current["setup_id"] != setup["id"] or current["profile_id"] != profile["id"]
        ):
            backup_slot = create_backup(target, current)
        snapshot = snapshot_files(target)
        try:
            for relative, data in files.items():
                atomic_write(safe_target_path(target, relative), data, target)
            atomic_write(stamp_path(target), canonical_json(desired_stamp), target)
        except BaseException:
            restore_snapshot(target, snapshot)
            raise
        return {
            "setup_id": setup["id"],
            "profile_id": profile["id"],
            "changed": changed,
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
        backup_slot = create_backup(target, current)
        files = desired_files(target, setup, profile)
        desired_stamp = build_stamp(target, setup["id"], profile["id"], files)
        snapshot = snapshot_files(target, extra_paths=sorted(current["managed_files"]))
        try:
            for relative, data in files.items():
                atomic_write(safe_target_path(target, relative), data, target)
            atomic_write(stamp_path(target), canonical_json(desired_stamp), target)
        except BaseException:
            restore_snapshot(target, snapshot)
            raise
        return {
            "setup_id": setup["id"],
            "profile_id": profile["id"],
            "source_legacy_setup_id": current["setup_id"],
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
        snapshot = snapshot_files(target, extra_paths=sorted(files))
        try:
            for relative, data in sorted(files.items()):
                path = safe_target_path(target, relative)
                atomic_write(path, data, target)
            prune_empty_managed_dirs(target)
            restored_stamp = validate_restored_state(target, expected_stamp)
        except BaseException:
            restore_snapshot(target, snapshot)
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
        return {"removed_setup_id": None, "target": str(validate_target(target, create=False))}
    with target_lock(target, create=False) as target:
        stamp = read_stamp(target)
        if stamp is None:
            return {"removed_setup_id": None, "target": str(validate_target(target, create=False))}
        drift = drift_for_stamp(target, stamp)
        if drift:
            fail(f"managed target has drift: {', '.join(drift)}")
        removed_setup_id = stamp["setup_id"]
        removed_profile_id = stamp.get("profile_id")
        snapshot = snapshot_files(target, extra_paths=sorted(stamp["managed_files"]))
        try:
            for relative in sorted(stamp["managed_files"]):
                path = safe_target_path(target, relative)
                if relative in MERGED_MARKER_PATHS:
                    remove_managed_block_from_target(target, relative)
                else:
                    with contextlib.suppress(FileNotFoundError):
                        path.unlink()
            with contextlib.suppress(FileNotFoundError):
                stamp_path(target).unlink()
            prune_empty_managed_dirs(target)
        except BaseException:
            restore_snapshot(target, snapshot)
            raise
        return {
            "removed_setup_id": removed_setup_id,
            "removed_profile_id": removed_profile_id,
            "removed_legacy": is_legacy_stamp(stamp),
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
        path.unlink()


def prune_empty_managed_dirs(target: Path) -> None:
    candidates: set[Path] = set()
    for relative in content_managed_paths():
        directory = safe_target_path(target, relative).parent
        while directory != target and target in directory.parents:
            candidates.add(directory)
            directory = directory.parent
    directories = sorted(candidates, key=lambda item: len(item.parts), reverse=True)
    for directory in directories:
        with contextlib.suppress(OSError):
            directory.rmdir()


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
        (software_container(target), ".nddev-software"),
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


def snapshot_optional_software_file(path: Path, label: str) -> tuple[bytes | None, int | None]:
    if not path.exists() and not path.is_symlink():
        return None, None
    data = read_software_file(path, label)
    info = require_software_regular_file(path, label)
    return data, stat.S_IMODE(info.st_mode)


def software_file_mode_is(path: Path, mode: int) -> bool:
    info = path.lstat()
    return not stat.S_ISLNK(info.st_mode) and stat.S_IMODE(info.st_mode) == mode


def software_atomic_write(path: Path, data: bytes, target: Path, mode: int) -> None:
    ensure_private_parent(path, target)
    temporary = path.with_name(f".{path.name}.nddev.tmp.{os.getpid()}.{time.time_ns()}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise


def remove_empty_directory_if_created(path: Path, existed_before: bool) -> None:
    if existed_before:
        return
    with contextlib.suppress(FileNotFoundError, OSError):
        path.rmdir()


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
    return read_lifecycle_payload(target, software_status_locked)


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
            before_container_exists = (
                software_container(target).exists() or software_container(target).is_symlink()
            )
            before_root_exists = (
                software_root(target).exists() or software_root(target).is_symlink()
            )
            before_versions_exists = (
                software_versions_dir(target).exists() or software_versions_dir(target).is_symlink()
            )
            before_version_exists = (
                software_version_dir(target).exists() or software_version_dir(target).is_symlink()
            )
            before_bin_dir_exists = (
                managed_grok_path(target).parent.exists()
                or managed_grok_path(target).parent.is_symlink()
            )
            before_binary, before_binary_mode = snapshot_optional_software_file(
                managed_grok_path(target), "bin/grok"
            )
            before_stamp, before_stamp_mode = snapshot_optional_software_file(
                software_stamp_path(target), SOFTWARE_STAMP_NAME
            )
            installer, installer_sha256, installer_source = read_pinned_installer()
            artifact = run_vendor_installer(installer, installer_source, installer_sha256, target)
            stamp_bytes = canonical_json(
                software_stamp(
                    target,
                    installer_source=artifact["installer_source"],
                    installer_sha256=artifact["installer_sha256"],
                    binary_sha256=artifact["binary_sha256"],
                    version_output=artifact["version_output"],
                )
            )
            staging: Path | None = None
            rollback_parent: Path | None = None
            rollback: Path | None = None
            version_dir = software_version_dir(target)
            try:
                ensure_private_directory(software_container(target), ".nddev-software")
                ensure_private_directory(software_root(target), ".nddev-software/grok-build")
                ensure_private_directory(
                    software_versions_dir(target), ".nddev-software/grok-build/versions"
                )
                if before_version_exists:
                    require_private_directory(
                        version_dir, f".nddev-software/grok-build/versions/{GROK_VERSION}"
                    )
                staging = Path(
                    tempfile.mkdtemp(prefix=".stage-", dir=str(software_versions_dir(target)))
                )
                rollback_parent = Path(
                    tempfile.mkdtemp(prefix=".rollback-", dir=str(software_versions_dir(target)))
                )
                rollback = rollback_parent / GROK_VERSION
                software_atomic_write(
                    staging / GROK_COMMAND, artifact["binary"], target, OWNER_EXEC_MODE
                )
                if before_version_exists:
                    version_dir.rename(rollback)
                staging.rename(version_dir)
                software_atomic_write(
                    managed_grok_path(target), artifact["binary"], target, OWNER_EXEC_MODE
                )
                software_atomic_write(
                    software_stamp_path(target), stamp_bytes, target, OWNER_FILE_MODE
                )
                final_status = software_status_locked(target)
                if not final_status["installed"]:
                    fail(
                        "Grok Build software install did not produce structurally complete target-owned software"
                    )
                if not final_status["current"]:
                    fail("Grok Build software install did not produce current pinned software")
            except BaseException:
                if version_dir.exists() or version_dir.is_symlink():
                    if version_dir.is_dir() and not version_dir.is_symlink():
                        shutil.rmtree(version_dir)
                    else:
                        version_dir.unlink()
                if rollback is not None and rollback.exists():
                    rollback.rename(version_dir)
                if before_binary is None:
                    with contextlib.suppress(FileNotFoundError):
                        managed_grok_path(target).unlink()
                else:
                    software_atomic_write(
                        managed_grok_path(target),
                        before_binary,
                        target,
                        before_binary_mode or OWNER_EXEC_MODE,
                    )
                if before_stamp is None:
                    with contextlib.suppress(FileNotFoundError):
                        software_stamp_path(target).unlink()
                else:
                    software_atomic_write(
                        software_stamp_path(target),
                        before_stamp,
                        target,
                        before_stamp_mode or OWNER_FILE_MODE,
                    )
                if staging is not None:
                    with contextlib.suppress(FileNotFoundError):
                        shutil.rmtree(staging)
                if rollback_parent is not None:
                    with contextlib.suppress(FileNotFoundError):
                        shutil.rmtree(rollback_parent)
                remove_empty_directory_if_created(
                    managed_grok_path(target).parent, before_bin_dir_exists
                )
                remove_empty_directory_if_created(
                    software_versions_dir(target), before_versions_exists
                )
                remove_empty_directory_if_created(software_root(target), before_root_exists)
                remove_empty_directory_if_created(
                    software_container(target), before_container_exists
                )
                raise
            if rollback_parent is not None:
                with contextlib.suppress(FileNotFoundError):
                    shutil.rmtree(rollback_parent)
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
                    f".nddev-software/grok-build/versions/{GROK_VERSION}/grok",
                    f".nddev-software/grok-build/{SOFTWARE_STAMP_NAME}",
                ],
                "installer_sha256": artifact["installer_sha256"],
                "binary_sha256": artifact["binary_sha256"],
                "managed_command": str(managed_grok_path(target).resolve(strict=False)),
            }
        except BaseException:
            remove_empty_directory_if_created(target, before_target_exists)
            raise


def plan_payload(target: Path, setup: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    status = read_lifecycle_payload(target, status_payload_locked)
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
        "target": str(status["canonical_target"]),
        "current_setup_id": status["setup_id"],
        "current_profile_id": status["profile_id"],
        "current_schema_version": status["schema_version"],
        "drift": status["drift"],
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


def validate_launch_workspace(raw_workspace: str | None) -> tuple[Path, str]:
    if raw_workspace is None:
        try:
            workspace = Path.cwd().resolve(strict=True)
        except OSError as exc:
            fail(f"launch workspace cannot be captured from the caller cwd: {exc}")
        require_real_directory(workspace, "launch workspace")
        return workspace, "caller-cwd"
    workspace = Path(raw_workspace)
    if not workspace.is_absolute():
        fail("launch workspace must be an absolute path")
    if workspace.name in ("", ".", ".."):
        fail("launch workspace must name a directory")
    require_real_directory(workspace, "launch workspace")
    return workspace.resolve(strict=True), "explicit"


def launch(target: Path, child_args: list[str], *, workspace: str | None = None) -> int:
    require_supported_runtime_platform()
    override = child_args_use_target_scope_overrides(child_args)
    if override is not None:
        fail(f"launch child arguments must not override target-owned Grok Build scope: {override}")
    mutation = managed_launch_mutation(child_args)
    if mutation is not None:
        fail(f"launch denied for Grok Build managed-state mutation: {mutation}")
    launch_workspace, _workspace_source = validate_launch_workspace(workspace)
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
                [str(launch_image), "--cwd", str(launch_workspace), *child_args],
                env=child_env,
                cwd=launch_workspace,
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
    for name in ("status", "remove", "software-status", "install-cli", "update-cli"):
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
    launch_parser.add_argument("--workspace")
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
    if args.command == "launch":
        child_args = list(args.child_args)
        if child_args[:1] == ["--"]:
            child_args = child_args[1:]
        return launch(require_absolute_target(args.target), child_args, workspace=args.workspace)
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
