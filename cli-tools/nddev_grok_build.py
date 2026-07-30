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
import io
import json
import os
import platform
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath
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
ROLLBACK_INTENT_NAME = "NDDEV-GROK-BUILD-ROLLBACK.json"
STAMP_SCHEMA_VERSION = 2
LEGACY_STAMP_SCHEMA_VERSION = 1
SOFTWARE_STAMP_SCHEMA_VERSION = 2
CLEANUP_JOURNAL_SCHEMA_VERSION = 1
ROLLBACK_INTENT_SCHEMA_VERSION = 1
MANAGED_BEGIN = "# BEGIN NDDEV-GROK-BUILD MANAGED"
MANAGED_END = "# END NDDEV-GROK-BUILD MANAGED"
OWNER_FILE_MODE = 0o600
OWNER_DIRECTORY_MODE = 0o700
OWNER_EXEC_MODE = 0o700
IMMUTABLE_EXEC_MODE = 0o500
LOCK_PARENT_HELD_MODE = 0o500
LOCK_DIR_NAME = "locks"
BOOTSTRAP_LOCK_SCHEMA_VERSION = 1
PRODUCT_LOCK_FILE_NAME = "global.lock"
PRODUCT_LOCK_NAMESPACE = f"{PRODUCT_NAME}:product-lock:v1"
TARGET_LOCK_ROOT_NAME = "target-locks"
TARGET_LOCK_SUFFIX = ".lock"
TARGET_LOCK_NAMESPACE = f"{PRODUCT_NAME}:target-lock:v1"
BOOTSTRAP_LOCK_NAMESPACE = TARGET_LOCK_NAMESPACE
MANAGED_MAX_BYTES = 8 * 1024 * 1024
METADATA_MAX_BYTES = 256 * 1024
CLEANUP_JOURNAL_MAX_BYTES = 32 * 1024 * 1024
SOFTWARE_MAX_BYTES = 256 * 1024 * 1024
ROLLBACK_MAX_ATTEMPTS = 8
READ_LIFECYCLE_MAX_ATTEMPTS = 4
GROK_COMMAND = "grok"
GROK_VERSION = "0.2.114"
GROK_CHANNEL = "stable"
GROK_NPM_PACKAGE = "@xai-official/grok"
GROK_NPM_INTEGRITY = "sha512-8eeyj6o0hQqzG5vr26CVixy1Fm3BkLhZzOnS7JXKVGuELpyw7N9MuVSs/xJyDUDdUYWhlsDnu+wMXWLiqj7XPg=="
GROK_NPM_SHASUM = "1da7b276d788193af17d6d5ff78e871988d6426c"
GROK_NPM_TARBALL = "https://registry.npmjs.org/@xai-official/grok/-/grok-0.2.114.tgz"
GROK_NPM_TARBALL_MAX_BYTES = 1 * 1024 * 1024
GROK_NPM_UNPACKED_SIZE = 17281
GROK_NPM_FILE_COUNT = 4
NPM_NATIVE_TARBALL_MAX_BYTES = 96 * 1024 * 1024
NODE_MINIMUM_MAJOR = 20
NODE_CANDIDATE_PATHS = (
    Path("/opt/homebrew/bin/node"),
    Path("/usr/local/bin/node"),
    Path("/usr/bin/node"),
    Path("/bin/node"),
)
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
CLEANUP_JOURNAL_NAME = "NDDEV-GROK-BUILD-CLEANUP.json"
CLEANUP_ROOT_RELATIVE = f"{CONTROL_DIR_NAME}/cleanup"
CLEANUP_JOURNAL_RELATIVE = f"{CLEANUP_ROOT_RELATIVE}/{CLEANUP_JOURNAL_NAME}"
CLEANUP_TOMBSTONE_PARENT_RELATIVE = f"{CONTROL_DIR_NAME}/tmp"
CLEANUP_MAX_ROOTS = 8
CLEANUP_MAX_ENTRIES = 4096
CLEANUP_MAX_ROOT_NAME_BYTES = 96
CLEANUP_MAX_RELATIVE_BYTES = 240
CLEANUP_TOMBSTONE_ROOT_PREFIXES = ("rollback.", "backup.")
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
HOST_PREFLIGHT_COMMANDS = {
    "status",
    "software-status",
    "plan",
    "install",
    "update",
    "switch",
    "migrate",
    "restore",
    "remove",
    "install-cli",
    "update-cli",
    "remove-cli",
    "launch",
}
SUPPORTED_MACHINE_ARCHITECTURES = ("aarch64", "x86_64")
HOST_ARCH_BY_MACHINE_ARCH = {
    "aarch64": "arm64",
    "x86_64": "x64",
}
VENDOR_INSTALLER_ASSET_BY_HOST_ID = {
    "macos-arm64": "grok-0.2.114-macos-aarch64",
    "macos-x64": "grok-0.2.114-macos-x86_64",
    "ubuntu-glibc-arm64": "grok-0.2.114-linux-aarch64",
    "ubuntu-glibc-x64": "grok-0.2.114-linux-x86_64",
}
VENDOR_UNSUPPORTED_WINDOWS_ASSET_BY_ARCH = {
    "aarch64": "grok-0.2.114-windows-aarch64.exe",
    "x86_64": "grok-0.2.114-windows-x86_64.exe",
}
NPM_NATIVE_PACKAGE_BY_HOST_ID: dict[str, dict[str, Any]] = {
    "macos-arm64": {
        "package": "@xai-official/grok-darwin-arm64",
        "integrity": "sha512-ZTvkr+5vwQ7LomzBnWMflgLZB2qVmhdFEt6by4EIdEO4DYTa9VQ4HZftkgxDQkf3sF8NxgDSE3jVYViWjiNDew==",
        "shasum": "0d9c102cdf5b4176af60f825dfcddb8821bfb12a",
        "tarball": "https://registry.npmjs.org/@xai-official/grok-darwin-arm64/-/grok-darwin-arm64-0.2.114.tgz",
        "unpacked_size": 37239049,
        "file_count": 4,
        "os": "darwin",
        "cpu": "arm64",
        "binary_member": "package/bin/grok.br",
    },
    "macos-x64": {
        "package": "@xai-official/grok-darwin-x64",
        "integrity": "sha512-tnExO3BY1ohk2G3CXQ76+HS2DCSoh37ZU4sk5tAYb/WlzX+zVTOIi4YwGalQZ4EfBrHl0rmucb8VTodfAz/RXQ==",
        "shasum": "e38c7057dfe352a9504a5daec3ec430d02f82450",
        "tarball": "https://registry.npmjs.org/@xai-official/grok-darwin-x64/-/grok-darwin-x64-0.2.114.tgz",
        "unpacked_size": 43308066,
        "file_count": 4,
        "os": "darwin",
        "cpu": "x64",
        "binary_member": "package/bin/grok.br",
    },
    "ubuntu-glibc-arm64": {
        "package": "@xai-official/grok-linux-arm64",
        "integrity": "sha512-GpiPA3tUfzIzjDW188Evz0iD1Qa7N25gV1DaHZOwfBqlm55wBjk1zs74pKiT06IfoHb/8qjigKlbzmGCrxhg4A==",
        "shasum": "12ea5e19c1e4a1ab14a52c7e0abf11600b28d321",
        "tarball": "https://registry.npmjs.org/@xai-official/grok-linux-arm64/-/grok-linux-arm64-0.2.114.tgz",
        "unpacked_size": 40301752,
        "file_count": 4,
        "os": "linux",
        "cpu": "arm64",
        "binary_member": "package/bin/grok.br",
    },
    "ubuntu-glibc-x64": {
        "package": "@xai-official/grok-linux-x64",
        "integrity": "sha512-LjfqwRkFNplAwph9EMsLxAzbVPQewQp60rF+/l3x1EsTa43yW7zyVbZpPVWXXcev1TQ9K87qqmqhbUMU/E0Q3w==",
        "shasum": "49cdcafd402fdd30948e9bfb466a8531f3a40384",
        "tarball": "https://registry.npmjs.org/@xai-official/grok-linux-x64/-/grok-linux-x64-0.2.114.tgz",
        "unpacked_size": 45386913,
        "file_count": 4,
        "os": "linux",
        "cpu": "x64",
        "binary_member": "package/bin/grok.br",
    },
}
NPM_UNSUPPORTED_NATIVE_PACKAGE_OBSERVATIONS: dict[str, dict[str, Any]] = {
    "@xai-official/grok-win32-x64": {
        "integrity": "sha512-xrBENcmX2ChPmTOMiYod5nbVjkYcuPZ3/sFJ7OLUDHyjMYUME3NJUuN2sO8kBbYwGRvdiMO2D6AK6OJeUcmJow==",
        "shasum": "b2e9df8e5ca0bd6e48783aafd4c904b411632109",
        "unpacked_size": 40804870,
    },
    "@xai-official/grok-win32-arm64": {
        "integrity": "sha512-LSQfzL3+engKov1WA/X3QLh7vxvftVFfZEe1twfkYs2iuTxyJ8rgd4JymYA0hP1SEX9RFryllNZSsHRkQqgF9A==",
        "shasum": "fc45a94d5b627f89eab8489bbe1105172375a2a2",
        "unpacked_size": 36877084,
    },
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


class ReadLifecycleRetry(Exception):
    """Internal signal that a cold read raced anchor publication."""


class PostCommitCleanupError(GrokBuildSetupError):
    """Cleanup failure after the active lifecycle state has committed."""


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
    mtime_ns: int | None = None
    dev: int | None = None
    ino: int | None = None


class PreservedFile(NamedTuple):
    target: Path
    path: Path
    label: str
    max_bytes: int
    snapshot: FileSnapshot
    stage_root: Path
    parent_mtime_ns: int | None
    backup_path: Path | None


class TreeEntry(NamedTuple):
    kind: str
    mode: int | None
    data: bytes | None
    size: int | None = None
    dev: int | None = None
    ino: int | None = None
    mtime_ns: int | None = None
    uid: int | None = None
    nlink: int | None = None


class PreservedTree(NamedTuple):
    target: Path
    path: Path
    label: str
    max_bytes: int
    snapshot: dict[str, TreeEntry]
    stage_root: Path | None
    parent_mtime_ns: int | None
    backup_path: Path | None


class BackupTransaction(NamedTuple):
    slot: int
    stage_root: Path
    stage_path: Path
    envelope: dict[str, Any]


class BackupCommit(NamedTuple):
    slot: int | None
    preserved_files: dict[str, PreservedFile]
    cleanup_roots: list[Path]


class LifecycleSnapshot(NamedTuple):
    files: dict[str, FileSnapshot]
    control_root_dir: TreeEntry
    cleanup_root_dir: TreeEntry
    backup_pool: dict[str, TreeEntry]
    control_tmp: dict[str, TreeEntry]
    lock_parent: dict[str, TreeEntry]
    launch_images: dict[str, TreeEntry]
    preserved_files: dict[str, PreservedFile]


class SoftwareSnapshot(NamedTuple):
    control_root_dir: TreeEntry
    cleanup_root_dir: TreeEntry
    software_root: dict[str, TreeEntry]
    software_container_dir: TreeEntry
    managed_binary: FileSnapshot
    managed_bin_dir: TreeEntry
    control_tmp: dict[str, TreeEntry]
    lock_parent: dict[str, TreeEntry]
    preserved_files: dict[str, PreservedFile]
    preserved_trees: dict[str, PreservedTree]


class BootstrapLockHandle(NamedTuple):
    descriptor: int
    path: Path
    product_root: Path
    system_root: Path
    file_preexisting: bool
    product_root_preexisting: bool
    product_root_mtime_ns: int | None
    system_root_mtime_ns: int | None


class ProductLockHandle(NamedTuple):
    descriptor: int
    path: Path
    product_root: Path
    system_root: Path
    mode: int


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


class ExternalTargetLockHandle(NamedTuple):
    descriptor: int
    path: Path
    canonical_target: str


class TargetCoordination(NamedTuple):
    target: Path
    created_parent_chain: list[Path]
    remove_empty_target: bool
    missing: bool
    created_target_parent_snapshot: tuple[Path, TreeEntry] | None
    target_lock: ExternalTargetLockHandle | None


class JsonArgumentParseError(Exception):
    """argparse error that can be returned as one JSON payload."""


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise JsonArgumentParseError(message)


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
        remove_empty_directory_if_created(path, existed_before=False)


def restore_directory_entry_after_cleanup(path: Path, entry: TreeEntry, label: str) -> None:
    ensure_directory_entry(path, entry, label)
    fsync_directory(path.parent, f"{label} parent after cleanup")


def snapshot_created_target_parent(target: Path, *, create: bool) -> tuple[Path, TreeEntry] | None:
    if not create or target.exists() or target.is_symlink():
        return None
    try:
        parent = target.parent.resolve(strict=True)
    except FileNotFoundError:
        return None
    return (parent, snapshot_directory_entry(parent, "target parent"))


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


def product_anchor_path(product_root: Path) -> Path:
    return product_root / PRODUCT_LOCK_FILE_NAME


def target_lock_root_path(product_root: Path) -> Path:
    return product_root / TARGET_LOCK_ROOT_NAME


def bootstrap_target_identity(target: Path) -> str:
    return lexical_target_identity(target)


def bootstrap_lock_digest(identity: str) -> str:
    payload = f"{TARGET_LOCK_NAMESPACE}\n{identity}\n".encode("utf-8")
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


def read_lock_binding(descriptor: int, *, label: str) -> bytes | None:
    size = os.fstat(descriptor).st_size
    if size == 0:
        return None
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
            fail("cleanup journal is too large")
        chunks.append(chunk)
    data = b"".join(chunks)
    if len(data) > METADATA_MAX_BYTES:
        fail(f"{label} binding is too large")
    return data


def read_product_lock_binding(descriptor: int) -> bytes:
    data = read_lock_binding(descriptor, label="product lock")
    if data is None:
        fail("product lock binding is missing")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"product lock binding is invalid JSON: {exc}")
    validate_product_lock_binding(value)
    if data != expected_product_lock_binding_bytes():
        fail("product lock binding is not canonical")
    return data


def read_bootstrap_lock_binding(descriptor: int, identity: str) -> bytes | None:
    data = read_lock_binding(descriptor, label="target lock")
    if data is None:
        return None
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"target lock binding is invalid JSON: {exc}")
    validate_bootstrap_lock_binding(value, identity)
    if data != expected_bootstrap_lock_binding_bytes(identity):
        fail("target lock binding is not canonical")
    return data


def cleanup_anchor_temporary(path: Path, label: str) -> None:
    first_error: BaseException | None = None
    for _attempt in range(ROLLBACK_MAX_ATTEMPTS):
        if not (path.exists() or path.is_symlink()):
            fsync_directory(path.parent, f"{label} temporary cleanup")
            return
        try:
            info = stat_existing(path, f"{label} temporary")
            if info is None:
                continue
            if not stat.S_ISREG(info.st_mode):
                fail(f"{label} temporary must be a regular file")
            require_current_user_owner(info, f"{label} temporary")
            path.unlink()
            fsync_directory(path.parent, f"{label} temporary cleanup")
            return
        except BaseException as exc:
            if first_error is None:
                first_error = exc
    if first_error is not None:
        fail(f"{label} temporary cleanup failed: {first_error}")
    fail(f"{label} temporary cleanup failed")


def anchor_final_is_complete(path: Path, identity: str | None) -> bool:
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return False
    try:
        if identity is None:
            require_product_lock_descriptor(descriptor, path, allow_recoverable_alias=True)
        else:
            require_bootstrap_lock_descriptor(
                descriptor, path, identity, allow_recoverable_alias=True
            )
    except GrokBuildSetupError:
        return False
    finally:
        os.close(descriptor)
    return True


def is_anchor_temporary_alias(path: Path, candidate: Path) -> bool:
    prefix = f".{path.name}."
    suffix = ".tmp"
    name = candidate.name
    if not name.startswith(prefix) or not name.endswith(suffix):
        return False
    middle = name[len(prefix) : -len(suffix)]
    parts = middle.split(".")
    if len(parts) != 2:
        return False
    return all(part.isdecimal() and 1 <= len(part) <= 20 for part in parts)


def recover_anchor_publication_alias(
    descriptor: int,
    path: Path,
    *,
    label: str,
    identity: str | None,
) -> None:
    if identity is None:
        opened = require_product_lock_descriptor(descriptor, path, allow_recoverable_alias=True)
    else:
        opened = require_bootstrap_lock_descriptor(
            descriptor, path, identity, allow_recoverable_alias=True
        )
    if opened.st_nlink == 1:
        return
    if opened.st_nlink != 2:
        fail(f"{label} has an unknown hardlink count")
    aliases: list[Path] = []
    for candidate in sorted(path.parent.iterdir(), key=lambda item: item.name):
        if not is_anchor_temporary_alias(path, candidate):
            continue
        info = stat_existing(candidate, f"{label} publication alias")
        if info is None:
            continue
        if not stat.S_ISREG(info.st_mode):
            fail(f"{label} publication alias must be a regular file")
        require_current_user_owner(info, f"{label} publication alias")
        if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
            fail(f"{label} publication alias does not match the final anchor")
        aliases.append(candidate)
    if len(aliases) != 1:
        fail(f"{label} must have exactly one recoverable publication alias")
    try:
        aliases[0].unlink()
    except OSError as exc:
        fail(f"{label} publication alias cleanup failed: {exc}")
    fsync_directory(path.parent, f"{label} publication alias cleanup")
    if identity is None:
        require_product_lock_descriptor(descriptor, path)
    else:
        require_bootstrap_lock_descriptor(descriptor, path, identity)


def write_atomic_anchor(path: Path, data: bytes, mode: int, label: str) -> bool:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, mode)
    try:
        offset = 0
        while offset < len(data):
            written = os.write(descriptor, data[offset:])
            if written <= 0:
                fail(f"{label} binding write made no progress")
            offset += written
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        cleanup_anchor_temporary(temporary, label)
        raise
    os.close(descriptor)
    try:
        os.link(temporary, path)
    except FileExistsError:
        cleanup_anchor_temporary(temporary, label)
        return False
    except BaseException:
        cleanup_anchor_temporary(temporary, label)
        raise
    publication_error: BaseException | None = None
    for _attempt in range(ROLLBACK_MAX_ATTEMPTS):
        try:
            fsync_directory(path.parent, f"{label} publication")
            publication_error = None
            break
        except GrokBuildSetupError as exc:
            publication_error = exc
            if _attempt == ROLLBACK_MAX_ATTEMPTS - 1:
                break
    cleanup_anchor_temporary(temporary, label)
    if publication_error is not None:
        raise publication_error
    for _attempt in range(ROLLBACK_MAX_ATTEMPTS):
        try:
            fsync_directory(path.parent, f"{label} temporary cleanup")
            break
        except GrokBuildSetupError:
            if _attempt == ROLLBACK_MAX_ATTEMPTS - 1:
                raise
    return True


def require_product_lock_descriptor(
    descriptor: int, path: Path, *, allow_recoverable_alias: bool = False
) -> os.stat_result:
    opened = os.fstat(descriptor)
    if not stat.S_ISREG(opened.st_mode):
        fail("product lock must be a regular file")
    require_current_user_owner(opened, "product lock")
    allowed_link_counts = {1, 2} if allow_recoverable_alias else {1}
    if opened.st_nlink not in allowed_link_counts:
        fail("product lock has an unknown hardlink count")
    if stat.S_IMODE(opened.st_mode) != OWNER_FILE_MODE:
        fail("product lock must have mode 0600")
    current = stat_existing(path, "product lock")
    if current is None:
        fail("product lock disappeared while opening")
    if not stat.S_ISREG(current.st_mode):
        fail("product lock must be a regular file")
    require_current_user_owner(current, "product lock")
    if current.st_nlink not in allowed_link_counts or current.st_nlink != opened.st_nlink:
        fail("product lock has an unknown hardlink count")
    if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
        fail("product lock changed while opening")
    if stat.S_IMODE(current.st_mode) != OWNER_FILE_MODE:
        fail("product lock must have mode 0600")
    read_product_lock_binding(descriptor)
    return opened


def require_bootstrap_lock_descriptor(
    descriptor: int,
    path: Path,
    identity: str,
    *,
    allow_recoverable_alias: bool = False,
) -> os.stat_result:
    opened = os.fstat(descriptor)
    if not stat.S_ISREG(opened.st_mode):
        fail("target lock must be a regular file")
    require_current_user_owner(opened, "target lock")
    allowed_link_counts = {1, 2} if allow_recoverable_alias else {1}
    if opened.st_nlink not in allowed_link_counts:
        fail("target lock has an unknown hardlink count")
    if stat.S_IMODE(opened.st_mode) != OWNER_FILE_MODE:
        fail("target lock must have mode 0600")
    current = stat_existing(path, "target lock")
    if current is None:
        fail("target lock disappeared while opening")
    if not stat.S_ISREG(current.st_mode):
        fail("target lock must be a regular file")
    require_current_user_owner(current, "target lock")
    if current.st_nlink not in allowed_link_counts or current.st_nlink != opened.st_nlink:
        fail("target lock has an unknown hardlink count")
    if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
        fail("target lock changed while opening")
    if stat.S_IMODE(current.st_mode) != OWNER_FILE_MODE:
        fail("target lock must have mode 0600")
    binding = read_bootstrap_lock_binding(descriptor, identity)
    if binding is None:
        fail("target lock binding is missing")
    return opened


def publish_product_anchor_if_missing(product_root: Path) -> bool:
    path = product_anchor_path(product_root)
    if path.exists() or path.is_symlink():
        return False
    created = write_atomic_anchor(
        path,
        expected_product_lock_binding_bytes(),
        OWNER_FILE_MODE,
        "product lock",
    )
    if created:
        require_existing_managed_file(
            path, "product lock", max_bytes=METADATA_MAX_BYTES, expected_mode=OWNER_FILE_MODE
        )
    return created


def publish_target_anchor_if_missing(product_root: Path, identity: str) -> Path:
    root = target_lock_root_path(product_root)
    root_preexisting = root.exists() or root.is_symlink()
    product_root_mtime_ns = int(product_root.lstat().st_mtime_ns)
    root_mtime_ns: int | None = None
    target_anchor_published = False
    if not root_preexisting:
        root.mkdir(mode=OWNER_DIRECTORY_MODE)
        root.chmod(OWNER_DIRECTORY_MODE)
        fsync_directory(product_root, "target lock root creation")
    require_private_directory(root, "target lock root")
    if root_preexisting:
        root_mtime_ns = int(root.lstat().st_mtime_ns)
    path = bootstrap_lock_path_for_root(product_root, identity)
    if not (path.exists() or path.is_symlink()):
        try:
            target_anchor_published = write_atomic_anchor(
                path,
                expected_bootstrap_lock_binding_bytes(identity),
                OWNER_FILE_MODE,
                "target lock",
            )
        except BaseException:
            if anchor_final_is_complete(path, identity):
                raise
            if not root_preexisting and not target_anchor_published:
                with contextlib.suppress(OSError):
                    root.rmdir()
                with contextlib.suppress(OSError):
                    fsync_directory(product_root, "target lock root rollback")
                restore_directory_mtime(product_root, product_root_mtime_ns, "product lock root")
            elif root_preexisting and root_mtime_ns is not None:
                restore_directory_mtime(root, root_mtime_ns, "target lock root")
            raise
    return path


def restore_directory_mtime(path: Path, mtime_ns: int, label: str) -> None:
    try:
        current = path.lstat()
        os.utime(
            path,
            ns=(int(current.st_atime_ns), mtime_ns),
            follow_symlinks=False,
        )
    except PermissionError:
        return
    except OSError as exc:
        fail(f"{label} mtime restore failed: {exc}")
    if stat.S_ISDIR(current.st_mode):
        fsync_directory(path, f"{label} mtime restore")


def ensure_product_root_for_publication(system_root: Path) -> tuple[Path, bool, int | None, int]:
    system_info = require_real_directory(system_root, "system bootstrap root")
    system_root_mtime_ns = int(system_info.st_mtime_ns)
    product_root = bootstrap_product_root_path(system_root)
    product_root_preexisting = product_root.exists() or product_root.is_symlink()
    product_root_mtime_ns: int | None = None
    if product_root_preexisting:
        require_private_directory(product_root, "product lock root")
        product_root_mtime_ns = int(product_root.lstat().st_mtime_ns)
    else:
        product_root.mkdir(mode=OWNER_DIRECTORY_MODE)
        product_root.chmod(OWNER_DIRECTORY_MODE)
        require_private_directory(product_root, "product lock root")
        fsync_directory(system_root, "product lock root creation")
    return product_root, product_root_preexisting, product_root_mtime_ns, system_root_mtime_ns


def restore_unpublished_product_root(
    product_root: Path,
    *,
    product_root_preexisting: bool,
    product_root_mtime_ns: int | None,
    system_root: Path,
    system_root_mtime_ns: int,
    product_anchor_published: bool,
) -> None:
    if product_root_preexisting and product_root_mtime_ns is not None:
        restore_directory_mtime(product_root, product_root_mtime_ns, "product lock root")
        return
    if (
        product_anchor_published
        or product_anchor_path(product_root).exists()
        or product_anchor_path(product_root).is_symlink()
    ):
        return
    if product_root.exists() and not product_root.is_symlink():
        remove_empty_directory_if_created(product_root, existed_before=False)
    restore_directory_mtime(system_root, system_root_mtime_ns, "system product lock root")


def acquire_product_lock(*, create: bool, exclusive: bool) -> ProductLockHandle | None:
    system_root = bootstrap_system_root()
    product_root = bootstrap_product_root_path(system_root)
    product_root_preexisting = product_root.exists() or product_root.is_symlink()
    product_root_mtime_ns: int | None = None
    system_root_mtime_ns = int(
        require_real_directory(system_root, "system bootstrap root").st_mtime_ns
    )
    product_anchor_published = False
    if create:
        try:
            (
                product_root,
                product_root_preexisting,
                product_root_mtime_ns,
                system_root_mtime_ns,
            ) = ensure_product_root_for_publication(system_root)
            if not product_anchor_path(product_root).exists():
                product_anchor_published = publish_product_anchor_if_missing(product_root)
        except BaseException:
            restore_unpublished_product_root(
                product_root,
                product_root_preexisting=product_root_preexisting,
                product_root_mtime_ns=product_root_mtime_ns,
                system_root=system_root,
                system_root_mtime_ns=system_root_mtime_ns,
                product_anchor_published=product_anchor_published,
            )
            raise
    else:
        if not product_root_preexisting:
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
        opened = require_product_lock_descriptor(
            descriptor, path, allow_recoverable_alias=exclusive
        )
        needs_alias_recovery = exclusive and opened.st_nlink == 2
        lock_mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(descriptor, lock_mode)
        if needs_alias_recovery:
            recover_anchor_publication_alias(descriptor, path, label="product lock", identity=None)
        require_product_lock_descriptor(descriptor, path)
        return ProductLockHandle(
            descriptor=descriptor,
            path=path,
            product_root=product_root,
            system_root=system_root,
            mode=lock_mode,
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
        opened = require_bootstrap_lock_descriptor(
            descriptor, path, identity, allow_recoverable_alias=exclusive
        )
        needs_alias_recovery = exclusive and opened.st_nlink == 2
        lock_mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        if not blocking:
            lock_mode |= fcntl.LOCK_NB
        try:
            fcntl.flock(descriptor, lock_mode)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}:
                fail(f"target is locked: {path}")
            fail(f"target lock failed: {exc}")
        if needs_alias_recovery:
            recover_anchor_publication_alias(
                descriptor, path, label="target lock", identity=identity
            )
        require_bootstrap_lock_descriptor(descriptor, path, identity)
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


def acquire_bootstrap_lock_handle_for_identity(identity: str) -> BootstrapLockHandle:
    product = acquire_product_lock(create=True, exclusive=True)
    if product is None:
        fail("product lock was not created")
    target_lock: ExternalTargetLockHandle | None = None
    product_root = product.product_root
    system_root = product.system_root
    try:
        target_lock = open_external_target_lock(
            product_root,
            identity,
            exclusive=True,
            create=True,
            blocking=False,
        )
        if target_lock is None:
            fail("target lock was not created")
        release_product_lock(product)
        product = None
        return BootstrapLockHandle(
            descriptor=target_lock.descriptor,
            path=target_lock.path,
            product_root=product_root,
            system_root=system_root,
            file_preexisting=True,
            product_root_preexisting=True,
            product_root_mtime_ns=None,
            system_root_mtime_ns=None,
        )
    except BaseException:
        release_external_target_lock(target_lock)
        release_product_lock(product)
        raise


def acquire_bootstrap_lock(target: Path) -> int:
    product = acquire_product_lock(create=True, exclusive=True)
    if product is None:
        fail("product lock was not created")
    target_lock: ExternalTargetLockHandle | None = None
    try:
        canonical = validate_target(target, create=False)
        identity = canonical_target_identity(canonical)
        target_lock = open_external_target_lock(
            product.product_root,
            identity,
            exclusive=True,
            create=True,
            blocking=False,
        )
        if target_lock is None:
            fail("target lock was not created")
        release_product_lock(product)
        product = None
        descriptor = target_lock.descriptor
        target_lock = None
        return descriptor
    finally:
        release_external_target_lock(target_lock)
        release_product_lock(product)


def release_bootstrap_lock(descriptor: int) -> None:
    with contextlib.suppress(OSError):
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    os.close(descriptor)


def release_bootstrap_lock_handle(handle: BootstrapLockHandle) -> None:
    release_bootstrap_lock(handle.descriptor)


def canonical_target_identity(target: Path) -> str:
    return str(target)


def cold_product_namespace_snapshot(product_root: Path) -> ColdProductNamespaceSnapshot:
    info = stat_existing(product_root, "product lock root")
    if info is None:
        return ColdProductNamespaceSnapshot(False, None, None, None, None, None, None, None, None)
    if not stat.S_ISDIR(info.st_mode):
        fail("product lock root must be a directory")
    require_current_user_owner(info, "product lock root")
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        fail("product lock root must have mode 0700")
    try:
        entries = sorted(product_root.iterdir(), key=lambda item: item.name)
    except FileNotFoundError:
        raise ReadLifecycleRetry
    except OSError as exc:
        fail(f"product lock namespace cannot be inspected: {exc}")
    if entries:
        product_anchor = product_anchor_path(product_root)
        for entry in entries:
            if entry.name == PRODUCT_LOCK_FILE_NAME:
                raise ReadLifecycleRetry
            if is_anchor_temporary_alias(product_anchor, entry):
                fail("product lock publication alias exists without product anchor")
            if entry.name == TARGET_LOCK_ROOT_NAME:
                fail("target lock namespace exists without product anchor")
        fail("product lock namespace must be empty without product anchor")
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
    while True:
        product = acquire_product_lock(create=False, exclusive=False)
        target_lock_handle: ExternalTargetLockHandle | None = None
        if product is None:
            system_root = bootstrap_system_root()
            product_root = bootstrap_product_root_path(system_root)
            before = cold_product_namespace_snapshot(product_root)
            canonical = validate_target(target, create=False)
            after_target = cold_product_namespace_snapshot(product_root)
            if after_target != before:
                raise ReadLifecycleRetry
            missing = not (canonical.exists() or canonical.is_symlink())
            try:
                yield TargetCoordination(canonical, [], False, missing, None, None)
            except GrokBuildSetupError:
                after_error = cold_product_namespace_snapshot(product_root)
                if after_error != before:
                    raise ReadLifecycleRetry
                raise
            except BaseException:
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
            missing = not (canonical.exists() or canonical.is_symlink())
            try:
                yield TargetCoordination(canonical, [], False, missing, None, target_lock_handle)
            except BaseException:
                raise
            if target_lock_handle is None:
                target_anchor = bootstrap_lock_path_for_root(product.product_root, identity)
                if target_anchor.exists() or target_anchor.is_symlink():
                    fail("target lock anchor appeared without coordination")
            return
        finally:
            release_external_target_lock(target_lock_handle)
            release_product_lock(product)


def read_lifecycle_payload(target: Path, reader: Any) -> Any:
    for attempt in range(READ_LIFECYCLE_MAX_ATTEMPTS):
        try:
            with read_lifecycle_coordination(target) as coordination:
                return reader(coordination.target)
        except ReadLifecycleRetry:
            if attempt + 1 >= READ_LIFECYCLE_MAX_ATTEMPTS:
                fail("read-only lifecycle coordination changed during inspection")
            continue
    fail("read-only lifecycle coordination changed during inspection")


@contextlib.contextmanager
def external_lifecycle_coordination(target: Path, *, create: bool, allow_missing: bool):
    product = acquire_product_lock(create=True, exclusive=True)
    if product is None:
        fail("product lock was not created")
    target_lock_handle: ExternalTargetLockHandle | None = None
    created_parent_chain: list[Path] = []
    remove_empty_target = False
    created_target_parent_snapshot: tuple[Path, TreeEntry] | None = None
    yielded = False
    try:
        created_target_parent_snapshot = snapshot_created_target_parent(target, create=create)
        created_parent_chain = missing_directory_chain(target.parent)
        remove_empty_target = create and not (target.exists() or target.is_symlink())
        target = validate_target(target, create=create)
        canonical_identity = canonical_target_identity(target)
        missing = not (target.exists() or target.is_symlink())
        if missing and not allow_missing:
            fail("target is missing")
        if not missing:
            target_lock_handle = open_external_target_lock(
                product.product_root,
                canonical_identity,
                exclusive=True,
                create=True,
                blocking=False,
            )
            if target_lock_handle is None:
                fail("target lock was not created")
            release_product_lock(product)
            product = None
        yielded = True
        yield TargetCoordination(
            target,
            created_parent_chain,
            remove_empty_target,
            missing,
            created_target_parent_snapshot,
            target_lock_handle,
        )
    finally:
        release_external_target_lock(target_lock_handle)
        release_product_lock(product)
        if not yielded:
            if remove_empty_target:
                remove_empty_directory_if_created(target, existed_before=False)
            remove_created_empty_directories(created_parent_chain)
            if created_target_parent_snapshot is not None:
                parent_path, parent_snapshot = created_target_parent_snapshot
                restore_directory_entry_after_cleanup(parent_path, parent_snapshot, "target parent")


@contextlib.contextmanager
def bootstrap_lifecycle_lock(target: Path):
    with read_lifecycle_coordination(target) as coordination:
        yield coordination.target


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


def launch_image_dir(target: Path) -> Path:
    return managed_control_dir(target) / "launch-images"


def cleanup_root_dir(target: Path) -> Path:
    return managed_control_dir(target) / "cleanup"


def cleanup_journal_path(target: Path) -> Path:
    return cleanup_root_dir(target) / CLEANUP_JOURNAL_NAME


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


def require_lockable_directory(path: Path, label: str, *, allow_locked: bool) -> os.stat_result:
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


def validate_backup_slot_topology(envelope_path: Path, label: str) -> None:
    slot_dir = envelope_path.parent
    pool = slot_dir.parent
    require_private_directory(pool, f"{label} pool")
    require_private_directory(slot_dir, f"{label} slot")
    entries = sorted(slot_dir.iterdir(), key=lambda item: item.name)
    if [entry.name for entry in entries] != [BACKUP_NAME]:
        fail(f"{label} slot must contain exactly {BACKUP_NAME}")
    envelope_info = require_existing_managed_file(
        envelope_path,
        BACKUP_NAME,
        max_bytes=METADATA_MAX_BYTES,
        expected_mode=OWNER_FILE_MODE,
    )
    if envelope_info is None:
        fail(f"{label} envelope is missing")
    if envelope_info.st_nlink != 1:
        fail(f"{label} envelope must not be a hardlink")


@contextlib.contextmanager
def target_lock(target: Path, *, create: bool, allow_missing: bool = False):
    created_parent_chain: list[Path] = []
    remove_empty_target = False
    restore_error: BaseException | None = None
    target_dir_snapshot: TreeEntry | None = None
    created_target_parent_snapshot: tuple[Path, TreeEntry] | None = None
    failed = False
    with external_lifecycle_coordination(
        target, create=create, allow_missing=allow_missing
    ) as coordination:
        target = coordination.target
        created_parent_chain = coordination.created_parent_chain
        remove_empty_target = coordination.remove_empty_target
        created_target_parent_snapshot = coordination.created_target_parent_snapshot
        try:
            if coordination.missing:
                try:
                    yield target
                except BaseException:
                    failed = True
                    raise
                return
            if not (
                cleanup_journal_path(target).exists() or cleanup_journal_path(target).is_symlink()
            ):
                recover_unjournaled_precommit_stages(target)
            drain_cleanup_journal(target)
            target_dir_snapshot = snapshot_directory_entry(target, "target")
            try:
                yield target
            except BaseException:
                failed = True
                raise
        finally:
            prune_empty_control_dirs(target)
            if remove_empty_target:
                remove_empty_directory_if_created(target, existed_before=False)
            remove_created_empty_directories(created_parent_chain)
            if failed and not remove_empty_target and target_dir_snapshot is not None:
                try:
                    restore_directory_entry_after_cleanup(target, target_dir_snapshot, "target")
                except BaseException as exc:
                    if restore_error is None:
                        restore_error = exc
            if failed and created_target_parent_snapshot is not None:
                parent_path, parent_snapshot = created_target_parent_snapshot
                try:
                    restore_directory_entry_after_cleanup(
                        parent_path, parent_snapshot, "target parent"
                    )
                except BaseException as exc:
                    if restore_error is None:
                        restore_error = exc
            if restore_error is not None:
                raise restore_error


def prune_empty_control_dirs(target: Path) -> None:
    for directory in (
        launch_image_dir(target),
        control_tmp_dir(target),
        backup_pool(target),
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
    if stat.S_IMODE(info.st_mode) & 0o022:
        fail(f"{label} must not be group- or world-writable")
    if expected_mode is not None and stat.S_IMODE(info.st_mode) != expected_mode:
        fail(f"{label} must have mode {expected_mode:04o}")
    if info.st_size > max_bytes:
        fail(f"{label} is too large")
    return info


def require_existing_file_stat_invariants(
    info: os.stat_result,
    label: str,
    *,
    max_bytes: int,
    expected_mode: int | None = None,
) -> None:
    if not stat.S_ISREG(info.st_mode):
        fail(f"{label} must be a regular file")
    require_current_user_owner(info, label)
    if info.st_nlink != 1:
        fail(f"{label} must not be a hardlink")
    mode = stat.S_IMODE(info.st_mode)
    if mode & 0o022:
        fail(f"{label} must not be group- or world-writable")
    if expected_mode is not None and mode != expected_mode:
        fail(f"{label} must have mode {expected_mode:04o}")
    if info.st_size > max_bytes:
        fail(f"{label} is too large")


def read_existing_file(
    path: Path, *, max_bytes: int, label: str, expected_mode: int | None = None
) -> bytes | None:
    before = require_existing_managed_file(
        path, label, max_bytes=max_bytes, expected_mode=expected_mode
    )
    if before is None:
        return None
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        fail(f"{label} open failed: {exc}")
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            fail(f"{label} changed while opening")
        require_existing_file_stat_invariants(
            opened, label, max_bytes=max_bytes, expected_mode=expected_mode
        )
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
    if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
        fail(f"{label} changed while reading")
    require_existing_file_stat_invariants(
        after, label, max_bytes=max_bytes, expected_mode=expected_mode
    )
    final = require_existing_managed_file(
        path, label, max_bytes=max_bytes, expected_mode=expected_mode
    )
    if final is None:
        fail(f"{label} disappeared while reading")
    if (
        final.st_dev,
        final.st_ino,
        final.st_size,
        final.st_mtime_ns,
        final.st_uid,
        final.st_nlink,
        stat.S_IMODE(final.st_mode),
    ) != (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_uid,
        before.st_nlink,
        stat.S_IMODE(before.st_mode),
    ):
        fail(f"{label} changed while reading")
    return b"".join(chunks)


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
        return FileSnapshot(None, None, None, None, None)
    data = read_existing_file(path, max_bytes=max_bytes, label=label)
    if data is None:
        fail(f"{label} disappeared while snapshotting")
    return FileSnapshot(
        data,
        stat.S_IMODE(info.st_mode),
        int(info.st_mtime_ns),
        int(info.st_dev),
        int(info.st_ino),
    )


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
    if stat.S_ISLNK(info.st_mode) or stat.S_IMODE(info.st_mode) != snapshot.mode:
        return False
    if snapshot.dev is not None and info.st_dev != snapshot.dev:
        return False
    if snapshot.ino is not None and info.st_ino != snapshot.ino:
        return False
    if snapshot.mtime_ns is not None and info.st_mtime_ns != snapshot.mtime_ns:
        return False
    return True


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


def preservation_stage_root(target: Path, label: str) -> Path:
    ensure_private_directory(managed_control_dir(target), "NDDev control root")
    ensure_private_directory(control_tmp_dir(target), "NDDev control tmp")
    digest = sha256_bytes(f"{label}\n{os.getpid()}\n{time.time_ns()}".encode("utf-8"))[:16]
    root = control_tmp_dir(target) / f"rollback.{digest}"
    ensure_private_directory(root, "NDDev rollback object store")
    return root


def cleanup_empty_preservation_stage_root(stage_root: Path) -> None:
    try:
        next(stage_root.iterdir())
    except FileNotFoundError:
        return
    except StopIteration:
        remove_empty_directory_if_created(stage_root, existed_before=False)
        remove_empty_directory_if_created(stage_root.parent, existed_before=False)
        remove_empty_directory_if_created(stage_root.parent.parent, existed_before=False)


def target_relative_path(target: Path, path: Path, label: str) -> str:
    try:
        relative = path.relative_to(target).as_posix()
    except ValueError:
        fail(f"{label} rollback source is outside the target")
    if (
        not relative
        or relative == "."
        or Path(relative).is_absolute()
        or ".." in Path(relative).parts
    ):
        fail(f"{label} rollback source is invalid")
    if len(relative.encode("utf-8")) > CLEANUP_MAX_RELATIVE_BYTES:
        fail(f"{label} rollback source is too long")
    return relative


def rollback_intent_path(stage_root: Path) -> Path:
    return stage_root / ROLLBACK_INTENT_NAME


def is_machine_rollback_stage_name(name: str) -> bool:
    return re.fullmatch(r"rollback\.[0-9a-f]{16}", name) is not None


def is_machine_backup_stage_name(name: str) -> bool:
    return re.fullmatch(r"backup\.[0-9]\.[0-9]{1,20}\.[0-9]{1,20}", name) is not None


def file_snapshot_payload(snapshot: FileSnapshot) -> dict[str, Any]:
    return {
        "present": snapshot.data is not None,
        "mode": snapshot.mode,
        "mtime_ns": snapshot.mtime_ns,
        "dev": snapshot.dev,
        "ino": snapshot.ino,
        "size": len(snapshot.data) if snapshot.data is not None else None,
        "sha256": sha256_bytes(snapshot.data) if snapshot.data is not None else None,
    }


def tree_entry_payload(entry: TreeEntry) -> dict[str, Any]:
    return cleanup_entry_payload(".", entry)


def tree_entry_from_payload(payload: Any, label: str) -> TreeEntry:
    if not isinstance(payload, dict) or set(payload) != {
        "path",
        "kind",
        "mode",
        "uid",
        "nlink",
        "size",
        "dev",
        "ino",
        "mtime_ns",
        "sha256",
    }:
        fail(f"{label} schema is invalid")
    if payload["path"] != ".":
        fail(f"{label} path is invalid")
    if payload["kind"] == "absent":
        return absent_tree_entry()
    if payload["kind"] != "dir":
        fail(f"{label} kind is invalid")
    return TreeEntry(
        "dir",
        payload["mode"],
        None,
        payload["size"],
        payload["dev"],
        payload["ino"],
        payload["mtime_ns"],
        payload["uid"],
        payload["nlink"],
    )


def tree_snapshot_payload(snapshot: dict[str, TreeEntry]) -> list[dict[str, Any]]:
    return [
        cleanup_entry_payload(relative, entry)
        for relative, entry in sorted(snapshot.items(), key=lambda item: item[0])
    ]


def rollback_entry_payload(entry: PreservedFile | PreservedTree, kind: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": kind,
        "source_kind": kind,
        "source_relative": target_relative_path(entry.target, entry.path, entry.label),
        "tombstone_relative": None if entry.backup_path is None else entry.backup_path.name,
        "label": entry.label,
        "max_bytes": entry.max_bytes,
        "parent_mtime_ns": entry.parent_mtime_ns,
    }
    if kind == "file":
        payload["snapshot"] = file_snapshot_payload(entry.snapshot)  # type: ignore[arg-type]
    elif kind == "tree":
        payload["snapshot"] = tree_snapshot_payload(entry.snapshot)  # type: ignore[arg-type]
    else:
        fail("rollback entry kind is invalid")
    return payload


def read_rollback_intent(stage_root: Path, target: Path) -> dict[str, Any]:
    path = rollback_intent_path(stage_root)
    if not (path.exists() or path.is_symlink()):
        fail("rollback stage is missing its recovery intent")
    payload = read_json_file(
        path,
        max_bytes=CLEANUP_JOURNAL_MAX_BYTES,
        label=ROLLBACK_INTENT_NAME,
        expected_mode=OWNER_FILE_MODE,
    )
    if set(payload) != {
        "schema_version",
        "product_name",
        "canonical_target",
        "target_directory",
        "stage_root",
        "entries",
    }:
        fail("rollback recovery intent schema is invalid")
    if payload["schema_version"] != ROLLBACK_INTENT_SCHEMA_VERSION:
        fail("rollback recovery intent schema is unsupported")
    if payload["product_name"] != PRODUCT_NAME:
        fail("rollback recovery intent belongs to another product")
    if payload["canonical_target"] != str(target):
        fail("rollback recovery intent is bound to another target")
    tree_entry_from_payload(payload["target_directory"], "rollback recovery target directory")
    if payload["stage_root"] != stage_root.name:
        fail("rollback recovery intent is bound to another stage")
    if not isinstance(payload["entries"], list) or len(payload["entries"]) > CLEANUP_MAX_ENTRIES:
        fail("rollback recovery intent entries are invalid")
    seen_sources: set[str] = set()
    seen_backups: set[str] = set()
    for item in payload["entries"]:
        if not isinstance(item, dict) or set(item) != {
            "kind",
            "source_kind",
            "source_relative",
            "tombstone_relative",
            "label",
            "max_bytes",
            "parent_mtime_ns",
            "snapshot",
        }:
            fail("rollback recovery intent entry schema is invalid")
        if item["kind"] not in {"file", "tree"}:
            fail("rollback recovery intent entry kind is invalid")
        if item["source_kind"] != item["kind"]:
            fail("rollback recovery intent source kind is invalid")
        source = item["source_relative"]
        if (
            not isinstance(source, str)
            or not source
            or source == "."
            or Path(source).is_absolute()
            or ".." in Path(source).parts
            or len(source.encode("utf-8")) > CLEANUP_MAX_RELATIVE_BYTES
        ):
            fail("rollback recovery intent source is invalid")
        if source in seen_sources:
            fail("rollback recovery intent has duplicate sources")
        seen_sources.add(source)
        backup = item["tombstone_relative"]
        if backup is not None:
            if (
                not isinstance(backup, str)
                or not backup
                or backup == ROLLBACK_INTENT_NAME
                or "/" in backup
                or "\\" in backup
                or backup in {".", ".."}
                or len(backup.encode("utf-8")) > CLEANUP_MAX_RELATIVE_BYTES
            ):
                fail("rollback recovery intent backup is invalid")
            if backup in seen_backups:
                fail("rollback recovery intent has duplicate backups")
            seen_backups.add(backup)
        if not isinstance(item["label"], str) or not item["label"]:
            fail("rollback recovery intent label is invalid")
        if not isinstance(item["max_bytes"], int) or item["max_bytes"] <= 0:
            fail("rollback recovery intent bound is invalid")
        parent_mtime_ns = item["parent_mtime_ns"]
        if parent_mtime_ns is not None and (
            not isinstance(parent_mtime_ns, int) or parent_mtime_ns < 0
        ):
            fail("rollback recovery intent parent mtime is invalid")
    return payload


def recover_empty_preintent_stage(target: Path, stage_root: Path, label: str) -> None:
    info = require_private_directory(stage_root, label)
    if stage_root.parent != control_tmp_dir(target):
        fail(f"{label} is outside the fixed cleanup parent")
    require_current_user_owner(info, label)
    try:
        next(stage_root.iterdir())
    except StopIteration:
        durable_rmdir(stage_root, label)
        return
    fail(f"{label} contains unknown pre-intent state")


def payload_file_snapshot_matches(
    path: Path, payload: dict[str, Any], max_bytes: int, label: str
) -> bytes:
    data = read_existing_file(path, max_bytes=max_bytes, label=label)
    if data is None:
        fail(f"{label} disappeared while reading rollback recovery state")
    info = require_existing_managed_file(path, label, max_bytes=max_bytes)
    if info is None:
        fail(f"{label} disappeared while reading rollback recovery state")
    expected_size = payload["size"]
    expected_sha = payload["sha256"]
    if (
        stat.S_IMODE(info.st_mode) != payload["mode"]
        or int(info.st_mtime_ns) != payload["mtime_ns"]
        or int(info.st_dev) != payload["dev"]
        or int(info.st_ino) != payload["ino"]
        or int(info.st_size) != expected_size
        or sha256_bytes(data) != expected_sha
    ):
        fail(f"{label} does not match rollback recovery authority")
    return data


def rollback_file_entry_from_intent(
    target: Path, stage_root: Path, item: dict[str, Any]
) -> PreservedFile:
    snapshot_payload = item["snapshot"]
    if not isinstance(snapshot_payload, dict) or set(snapshot_payload) != {
        "present",
        "mode",
        "mtime_ns",
        "dev",
        "ino",
        "size",
        "sha256",
    }:
        fail("rollback file recovery snapshot schema is invalid")
    source = target / item["source_relative"]
    backup = None if item["tombstone_relative"] is None else stage_root / item["tombstone_relative"]
    parent_mtime_ns = item["parent_mtime_ns"]
    if not snapshot_payload["present"]:
        return PreservedFile(
            target,
            source,
            item["label"],
            item["max_bytes"],
            FileSnapshot(None, None, None, None, None),
            stage_root,
            parent_mtime_ns,
            None,
        )
    if backup is not None and (backup.exists() or backup.is_symlink()):
        data = payload_file_snapshot_matches(
            backup, snapshot_payload, item["max_bytes"], item["label"]
        )
        return PreservedFile(
            target,
            source,
            item["label"],
            item["max_bytes"],
            FileSnapshot(
                data,
                snapshot_payload["mode"],
                snapshot_payload["mtime_ns"],
                snapshot_payload["dev"],
                snapshot_payload["ino"],
            ),
            stage_root,
            parent_mtime_ns,
            backup,
        )
    if source.exists() or source.is_symlink():
        data = payload_file_snapshot_matches(
            source, snapshot_payload, item["max_bytes"], item["label"]
        )
        return PreservedFile(
            target,
            source,
            item["label"],
            item["max_bytes"],
            FileSnapshot(
                data,
                snapshot_payload["mode"],
                snapshot_payload["mtime_ns"],
                snapshot_payload["dev"],
                snapshot_payload["ino"],
            ),
            stage_root,
            parent_mtime_ns,
            None,
        )
    fail(f"{item['label']} rollback recovery object disappeared")


def rollback_tree_payload_matches(snapshot: dict[str, TreeEntry], payload: Any, label: str) -> None:
    if not isinstance(payload, list):
        fail("rollback tree recovery snapshot schema is invalid")
    if tree_snapshot_payload(snapshot) != payload:
        fail(f"{label} does not match rollback recovery authority")


def rollback_tree_entry_from_intent(
    target: Path, stage_root: Path, item: dict[str, Any]
) -> PreservedTree:
    source = target / item["source_relative"]
    backup = None if item["tombstone_relative"] is None else stage_root / item["tombstone_relative"]
    parent_mtime_ns = item["parent_mtime_ns"]
    if backup is not None and (backup.exists() or backup.is_symlink()):
        snapshot = snapshot_tree(backup, max_bytes=item["max_bytes"], label=item["label"])
        rollback_tree_payload_matches(snapshot, item["snapshot"], item["label"])
        return PreservedTree(
            target,
            source,
            item["label"],
            item["max_bytes"],
            snapshot,
            stage_root,
            parent_mtime_ns,
            backup,
        )
    if source.exists() or source.is_symlink():
        snapshot = snapshot_tree(source, max_bytes=item["max_bytes"], label=item["label"])
        rollback_tree_payload_matches(snapshot, item["snapshot"], item["label"])
        return PreservedTree(
            target,
            source,
            item["label"],
            item["max_bytes"],
            snapshot,
            stage_root,
            parent_mtime_ns,
            None,
        )
    absent = {".": absent_tree_entry()}
    rollback_tree_payload_matches(absent, item["snapshot"], item["label"])
    return PreservedTree(
        target,
        source,
        item["label"],
        item["max_bytes"],
        absent,
        stage_root,
        parent_mtime_ns,
        None,
    )


def recover_rollback_stage(target: Path, stage_root: Path) -> TreeEntry:
    info = require_private_directory(stage_root, "rollback recovery stage")
    if stage_root.parent != control_tmp_dir(target) or not is_machine_rollback_stage_name(
        stage_root.name
    ):
        fail("rollback recovery stage is outside the fixed cleanup parent")
    require_current_user_owner(info, "rollback recovery stage")
    if not (
        rollback_intent_path(stage_root).exists() or rollback_intent_path(stage_root).is_symlink()
    ):
        recover_empty_preintent_stage(target, stage_root, "rollback recovery stage")
        return snapshot_directory_entry(target, "target")
    intent = read_rollback_intent(stage_root, target)
    expected_names = {ROLLBACK_INTENT_NAME}
    files: dict[str, PreservedFile] = {}
    trees: dict[str, PreservedTree] = {}
    for item in intent["entries"]:
        if (
            item["tombstone_relative"] is not None
            and (stage_root / item["tombstone_relative"]).exists()
        ):
            expected_names.add(item["tombstone_relative"])
        if item["kind"] == "file":
            files[item["source_relative"]] = rollback_file_entry_from_intent(
                target, stage_root, item
            )
        else:
            trees[item["source_relative"]] = rollback_tree_entry_from_intent(
                target, stage_root, item
            )
    actual_names = {entry.name for entry in stage_root.iterdir()}
    if actual_names != expected_names:
        fail("rollback recovery stage contains unknown state")
    restore_preserved_trees_retry(trees)
    restore_preserved_files_retry(files)
    remove_tree_until_absent_retry(
        stage_root, max_bytes=SOFTWARE_MAX_BYTES, label="rollback recovery stage"
    )
    return tree_entry_from_payload(intent["target_directory"], "rollback recovery target directory")


def recover_backup_stage(target: Path, stage_root: Path) -> None:
    info = require_private_directory(stage_root, "backup recovery stage")
    if stage_root.parent != control_tmp_dir(target) or not is_machine_backup_stage_name(
        stage_root.name
    ):
        fail("backup recovery stage is outside the fixed cleanup parent")
    require_current_user_owner(info, "backup recovery stage")
    actual_names = {entry.name for entry in stage_root.iterdir()}
    if not actual_names:
        recover_empty_preintent_stage(target, stage_root, "backup recovery stage")
        return
    if actual_names != {BACKUP_NAME}:
        fail("backup recovery stage contains unknown state")
    path = stage_root / BACKUP_NAME
    payload = read_json_file(
        path,
        max_bytes=METADATA_MAX_BYTES,
        label="backup recovery stage",
        expected_mode=OWNER_FILE_MODE,
    )
    slot = payload.get("slot")
    if not isinstance(slot, int):
        fail("backup recovery stage slot is invalid")
    validate_backup_envelope(target, slot, payload)
    remove_tree_until_absent_retry(
        stage_root, max_bytes=METADATA_MAX_BYTES, label="backup recovery stage"
    )


def recover_unjournaled_precommit_stages(target: Path) -> None:
    parent = control_tmp_dir(target)
    if not (parent.exists() or parent.is_symlink()):
        return
    require_private_directory(parent, "cleanup tombstone parent")
    rollback_stages: list[tuple[Path, bool]] = []
    backup_stages: list[Path] = []
    for entry in sorted(parent.iterdir(), key=lambda item: item.name):
        if is_machine_rollback_stage_name(entry.name):
            if not (
                rollback_intent_path(entry).exists() or rollback_intent_path(entry).is_symlink()
            ):
                recover_empty_preintent_stage(target, entry, "rollback recovery stage")
                continue
            intent = read_rollback_intent(entry, target)
            rollback_stages.append(
                (entry, any(item["kind"] == "tree" for item in intent["entries"]))
            )
        elif is_machine_backup_stage_name(entry.name):
            backup_stages.append(entry)
        else:
            fail("cleanup tombstone parent contains unknown pre-journal state")
    target_entries: list[TreeEntry] = []
    for entry, _has_tree in sorted(rollback_stages, key=lambda item: (not item[1], item[0].name)):
        target_entries.append(recover_rollback_stage(target, entry))
    for entry in backup_stages:
        recover_backup_stage(target, entry)
    remove_empty_directory_if_created(parent, existed_before=False)
    remove_empty_directory_if_created(cleanup_root_dir(target), existed_before=False)
    remove_empty_directory_if_created(managed_control_dir(target), existed_before=False)
    if target_entries:
        first = target_entries[0]
        if any(item != first for item in target_entries):
            fail("rollback recovery stages disagree on target identity")
        ensure_directory_entry(target, first, "target")


def write_rollback_intent(
    target: Path,
    stage_root: Path,
    entries: dict[str, PreservedFile | PreservedTree],
    target_entry: TreeEntry,
) -> None:
    ordered = sorted(
        entries.values(), key=lambda item: target_relative_path(target, item.path, item.label)
    )
    payload = {
        "schema_version": ROLLBACK_INTENT_SCHEMA_VERSION,
        "product_name": PRODUCT_NAME,
        "canonical_target": str(target),
        "target_directory": tree_entry_payload(target_entry),
        "stage_root": stage_root.name,
        "entries": [
            rollback_entry_payload(item, "tree" if isinstance(item, PreservedTree) else "file")
            for item in ordered
        ],
    }
    data = canonical_json(payload)
    if len(data) > CLEANUP_JOURNAL_MAX_BYTES:
        fail("cleanup journal exceeds the serialized byte limit")
    replace_file_durable(
        rollback_intent_path(stage_root),
        data,
        target,
        mode=OWNER_FILE_MODE,
        max_bytes=CLEANUP_JOURNAL_MAX_BYTES,
        label=ROLLBACK_INTENT_NAME,
        ensure_parent=ensure_private_parent,
        reader=read_existing_file,
    )
    read_rollback_intent(stage_root, target)
    ensure_cleanup_journal_projected_root_fits(
        target,
        stage_root,
        snapshot_tree(stage_root, max_bytes=SOFTWARE_MAX_BYTES, label="rollback stage"),
    )


def file_identity_snapshot(
    path: Path,
    *,
    max_bytes: int,
    label: str,
    reader: Any,
    expected_mode: int | None = None,
) -> FileSnapshot:
    info = require_existing_managed_file(
        path, label, max_bytes=max_bytes, expected_mode=expected_mode
    )
    if info is None:
        return FileSnapshot(None, None, None, None, None)
    data = reader(path, max_bytes=max_bytes, label=label)
    if data is None:
        fail(f"{label} disappeared while snapshotting")
    return FileSnapshot(
        data,
        stat.S_IMODE(info.st_mode),
        int(info.st_mtime_ns),
        int(info.st_dev),
        int(info.st_ino),
    )


def preserve_file_for_rollback(
    target: Path,
    path: Path,
    *,
    label: str,
    max_bytes: int,
    reader: Any,
    stage_root: Path,
    expected_mode: int | None = None,
    intent_entries: dict[str, PreservedFile | PreservedTree] | None = None,
    target_entry: TreeEntry | None = None,
) -> PreservedFile:
    if target_entry is None:
        target_entry = snapshot_directory_entry(target, "target")
    parent_mtime_ns = None
    with contextlib.suppress(OSError):
        parent_mtime_ns = int(path.parent.lstat().st_mtime_ns)
    snapshot = file_identity_snapshot(
        path,
        max_bytes=max_bytes,
        label=label,
        reader=reader,
        expected_mode=expected_mode,
    )
    if snapshot.data is None:
        entry = PreservedFile(
            target, path, label, max_bytes, snapshot, stage_root, parent_mtime_ns, None
        )
        if intent_entries is None:
            write_rollback_intent(target, stage_root, {label: entry}, target_entry)
        else:
            intent_entries[label] = entry
            write_rollback_intent(target, stage_root, intent_entries, target_entry)
        return entry
    backup_path = (
        stage_root / f"{len(list(stage_root.iterdir()))}.{sha256_bytes(str(path).encode('utf-8'))}"
    )
    if backup_path.exists() or backup_path.is_symlink():
        fail(f"{label} rollback object already exists")
    entry = PreservedFile(
        target, path, label, max_bytes, snapshot, stage_root, parent_mtime_ns, backup_path
    )
    moved = False
    try:
        if intent_entries is None:
            write_rollback_intent(target, stage_root, {label: entry}, target_entry)
        else:
            intent_entries[label] = entry
            write_rollback_intent(target, stage_root, intent_entries, target_entry)
        ensure_cleanup_journal_projected_file_fits(target, stage_root, backup_path, path, snapshot)
        os.replace(path, backup_path)
        moved = True
        fsync_directory(path.parent, f"{label} rollback object removal")
        fsync_directory(backup_path.parent, f"{label} rollback object preservation")
        return entry
    except OSError as exc:
        if moved:
            restore_preserved_files_retry({label: entry})
            cleanup_preserved_stage_roots_retry({label: entry})
        else:
            cleanup_empty_preservation_stage_root(stage_root)
        fail(f"{label} rollback object preservation failed: {exc}")
    except BaseException:
        if moved:
            restore_preserved_files_retry({label: entry})
            cleanup_preserved_stage_roots_retry({label: entry})
        else:
            cleanup_empty_preservation_stage_root(stage_root)
        raise


def restore_parent_mtime(entry: PreservedFile) -> None:
    if entry.parent_mtime_ns is None:
        return
    with contextlib.suppress(OSError):
        current = entry.path.parent.lstat()
        os.utime(
            entry.path.parent,
            ns=(int(current.st_atime_ns), entry.parent_mtime_ns),
            follow_symlinks=False,
        )
        fsync_directory(entry.path.parent, f"{entry.label} parent mtime restore")


def parent_mtime_matches(path: Path, expected_mtime_ns: int | None) -> bool:
    if expected_mtime_ns is None:
        return True
    try:
        return int(path.parent.lstat().st_mtime_ns) == expected_mtime_ns
    except OSError:
        return False


def preserved_file_matches(entry: PreservedFile) -> bool:
    return file_matches_snapshot(
        entry.path,
        entry.snapshot,
        max_bytes=entry.max_bytes,
        label=entry.label,
        reader=read_existing_file,
    ) and parent_mtime_matches(entry.path, entry.parent_mtime_ns)


def restore_preserved_file_once(entry: PreservedFile) -> None:
    if entry.snapshot.data is None:
        remove_file_until_absent_retry(entry.path, f"{entry.label} rollback absent")
        restore_parent_mtime(entry)
        return
    if file_matches_snapshot(
        entry.path,
        entry.snapshot,
        max_bytes=entry.max_bytes,
        label=entry.label,
        reader=read_existing_file,
    ):
        fsync_directory(entry.path.parent, f"{entry.label} rollback")
        restore_parent_mtime(entry)
        return
    if entry.backup_path is None or not (
        entry.backup_path.exists() or entry.backup_path.is_symlink()
    ):
        if entry.path.exists() or entry.path.is_symlink():
            restore_tree_file_entry(
                entry.path,
                TreeEntry(
                    "file",
                    entry.snapshot.mode,
                    entry.snapshot.data,
                    len(entry.snapshot.data),
                    entry.snapshot.dev,
                    entry.snapshot.ino,
                    entry.snapshot.mtime_ns,
                ),
                max_bytes=entry.max_bytes,
                label=entry.label,
            )
            restore_parent_mtime(entry)
            return
        fail(f"{entry.label} rollback object disappeared")
    if entry.path.exists() or entry.path.is_symlink():
        durable_unlink(entry.path, f"{entry.label} rollback replacement")
    ensure_private_parent(entry.path, entry.target)
    try:
        os.replace(entry.backup_path, entry.path)
    except OSError as exc:
        fail(f"{entry.label} rollback object restore failed: {exc}")
    fsync_directory(entry.path.parent, f"{entry.label} rollback restore")
    restore_parent_mtime(entry)


def restore_preserved_files_retry(entries: dict[str, PreservedFile]) -> None:
    for key in reversed(tuple(entries)):
        entry = entries[key]
        retry_until_exact(
            f"{entry.label} object rollback",
            lambda item=entry: preserved_file_matches(item),
            lambda item=entry: restore_preserved_file_once(item),
        )


def cleanup_preserved_files_retry(entries: dict[str, PreservedFile], stage_root: Path) -> None:
    for entry in entries.values():
        if entry.stage_root == stage_root and entry.backup_path is not None:
            remove_file_until_absent_retry(entry.backup_path, f"{entry.label} rollback cleanup")
    restore_tree_retry(
        stage_root,
        {".": TreeEntry("absent", None, None)},
        max_bytes=SOFTWARE_MAX_BYTES,
        label="rollback object store",
    )


def cleanup_preserved_stage_roots_retry(entries: dict[str, PreservedFile]) -> None:
    roots = {entry.stage_root for entry in entries.values()}
    for root in roots:
        cleanup_preserved_files_retry(entries, root)


def preserve_tree_for_rollback(
    target: Path,
    path: Path,
    *,
    label: str,
    max_bytes: int,
    intent_entries: dict[str, PreservedFile | PreservedTree] | None = None,
    target_entry: TreeEntry | None = None,
) -> PreservedTree:
    if target_entry is None:
        target_entry = snapshot_directory_entry(target, "target")
    parent_mtime_ns = None
    with contextlib.suppress(OSError):
        parent_mtime_ns = int(path.parent.lstat().st_mtime_ns)
    snapshot = snapshot_tree(path, max_bytes=max_bytes, label=label)
    if snapshot.get(".", absent_tree_entry()).kind == "absent":
        return PreservedTree(target, path, label, max_bytes, snapshot, None, parent_mtime_ns, None)
    stage_root = preservation_stage_root(target, f"{label} tree rollback")
    backup_path = stage_root / sha256_bytes(str(path).encode("utf-8"))
    if backup_path.exists() or backup_path.is_symlink():
        fail(f"{label} tree rollback object already exists")
    moved = False
    entry = PreservedTree(
        target, path, label, max_bytes, snapshot, stage_root, parent_mtime_ns, backup_path
    )
    try:
        if intent_entries is None:
            write_rollback_intent(target, stage_root, {label: entry}, target_entry)
        else:
            intent_entries[label] = entry
            write_rollback_intent(target, stage_root, intent_entries, target_entry)
        ensure_cleanup_journal_projected_tree_fits(target, stage_root, backup_path, snapshot)
        os.replace(path, backup_path)
        moved = True
        fsync_directory(path.parent, f"{label} tree rollback object removal")
        fsync_directory(stage_root, f"{label} tree rollback object preservation")
        return entry
    except OSError as exc:
        if moved:
            restore_preserved_trees_retry({label: entry})
            cleanup_preserved_tree_stage_roots_retry({label: entry})
        else:
            cleanup_empty_preservation_stage_root(stage_root)
        fail(f"{label} tree rollback object preservation failed: {exc}")
    except BaseException:
        if moved:
            restore_preserved_trees_retry({label: entry})
            cleanup_preserved_tree_stage_roots_retry({label: entry})
        else:
            cleanup_empty_preservation_stage_root(stage_root)
        raise


def restore_preserved_tree_once(entry: PreservedTree) -> None:
    if entry.snapshot.get(".", absent_tree_entry()).kind == "absent":
        remove_tree_until_absent_retry(entry.path, max_bytes=entry.max_bytes, label=entry.label)
        restore_tree_parent_mtime(entry)
        return
    if tree_matches_snapshot(
        entry.path, entry.snapshot, max_bytes=entry.max_bytes, label=entry.label
    ):
        fsync_directory(entry.path.parent, f"{entry.label} tree rollback")
        restore_tree_parent_mtime(entry)
        return
    if entry.backup_path is None:
        fail(f"{entry.label} tree rollback object is missing")
    if not (entry.backup_path.exists() or entry.backup_path.is_symlink()):
        if entry.path.exists() or entry.path.is_symlink():
            restore_tree_retry(
                entry.path,
                entry.snapshot,
                max_bytes=entry.max_bytes,
                label=entry.label,
            )
            restore_tree_parent_mtime(entry)
            return
        fail(f"{entry.label} tree rollback object disappeared")
    if entry.path.exists() or entry.path.is_symlink():
        remove_tree_until_absent_retry(
            entry.path, max_bytes=entry.max_bytes, label=f"{entry.label} tree replacement"
        )
    ensure_private_parent(entry.path, entry.target)
    try:
        os.replace(entry.backup_path, entry.path)
    except OSError as exc:
        fail(f"{entry.label} tree rollback object restore failed: {exc}")
    fsync_directory(entry.path.parent, f"{entry.label} tree rollback restore")
    restore_tree_parent_mtime(entry)


def restore_tree_parent_mtime(entry: PreservedTree) -> None:
    if entry.parent_mtime_ns is None:
        return
    with contextlib.suppress(OSError):
        current = entry.path.parent.lstat()
        os.utime(
            entry.path.parent,
            ns=(int(current.st_atime_ns), entry.parent_mtime_ns),
            follow_symlinks=False,
        )
        fsync_directory(entry.path.parent, f"{entry.label} tree parent mtime restore")


def preserved_tree_matches(entry: PreservedTree) -> bool:
    return tree_matches_snapshot(
        entry.path,
        entry.snapshot,
        max_bytes=entry.max_bytes,
        label=entry.label,
    ) and parent_mtime_matches(entry.path, entry.parent_mtime_ns)


def restore_preserved_trees_retry(entries: dict[str, PreservedTree]) -> None:
    for key in reversed(tuple(entries)):
        entry = entries[key]
        retry_until_exact(
            f"{entry.label} tree object rollback",
            lambda item=entry: preserved_tree_matches(item),
            lambda item=entry: restore_preserved_tree_once(item),
        )


def cleanup_preserved_tree_stage_roots_retry(entries: dict[str, PreservedTree]) -> None:
    roots = {entry.stage_root for entry in entries.values() if entry.stage_root is not None}
    for root in roots:
        remove_tree_until_absent_retry(
            root, max_bytes=SOFTWARE_MAX_BYTES, label="tree rollback object store"
        )


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
    vendor_installer_asset = (
        VENDOR_INSTALLER_ASSET_BY_HOST_ID.get(host_id) if host_id is not None else None
    )
    if platform_id == "windows":
        vendor_installer_asset = VENDOR_UNSUPPORTED_WINDOWS_ASSET_BY_ARCH.get(architecture)
    return RuntimePlatformInfo(
        system=system,
        platform_id=platform_id,
        host_id=host_id or platform_id,
        architecture=architecture,
        host_architecture=HOST_ARCH_BY_MACHINE_ARCH.get(architecture),
        vendor_installer_asset=vendor_installer_asset,
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


def require_command_supported_host(command: str) -> None:
    if command in HOST_PREFLIGHT_COMMANDS:
        require_supported_runtime_platform()


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
    require_supported_runtime_platform()
    return read_lifecycle_payload(target, status_payload_locked)


def status_payload_locked(target: Path) -> dict[str, Any]:
    canonical = validate_target(target, create=False)
    pending_cleanup = cleanup_pending_metadata(canonical)
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
            **pending_cleanup,
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
            **pending_cleanup,
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
            **pending_cleanup,
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
        **pending_cleanup,
    }


def snapshot_files(
    target: Path,
    extra_paths: tuple[str, ...] | list[str] | None = None,
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


def preserve_managed_files(
    target: Path, relative_paths: tuple[str, ...] | list[str], *, label: str
) -> dict[str, PreservedFile]:
    unique = tuple(dict.fromkeys(relative_paths))
    if not unique:
        return {}
    target_entry = snapshot_directory_entry(target, "target")
    stage_root = preservation_stage_root(target, label)
    preserved: dict[str, PreservedFile] = {}
    intent_entries: dict[str, PreservedFile | PreservedTree] = {}
    for relative in unique:
        preserved[relative] = preserve_file_for_rollback(
            target,
            safe_target_path(target, relative),
            label=relative,
            max_bytes=MANAGED_MAX_BYTES,
            reader=read_existing_file,
            stage_root=stage_root,
            intent_entries=intent_entries,
            target_entry=target_entry,
        )
    return preserved


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
    restore_snapshot_once(target, snapshot)
    retry_until_exact(
        "managed file rollback",
        lambda: managed_files_match_snapshot(target, snapshot),
        lambda: restore_snapshot_once(target, snapshot),
    )


def absent_tree_entry() -> TreeEntry:
    return TreeEntry("absent", None, None)


def tree_entry_from_stat(kind: str, info: os.stat_result, data: bytes | None) -> TreeEntry:
    return TreeEntry(
        kind,
        stat.S_IMODE(info.st_mode),
        data,
        int(info.st_size),
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mtime_ns),
        int(info.st_uid),
        int(info.st_nlink),
    )


def snapshot_tree(root: Path, *, max_bytes: int, label: str) -> dict[str, TreeEntry]:
    if not root.exists() and not root.is_symlink():
        return {".": absent_tree_entry()}
    info = stat_existing(root, label)
    if info is None:
        return {".": absent_tree_entry()}
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    require_current_user_owner(info, label)
    entries: dict[str, TreeEntry] = {".": tree_entry_from_stat("dir", info, None)}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        path_info = stat_existing(path, f"{label}/{relative}")
        if path_info is None:
            continue
        if stat.S_ISDIR(path_info.st_mode):
            require_current_user_owner(path_info, f"{label}/{relative}")
            entries[relative] = tree_entry_from_stat("dir", path_info, None)
            continue
        if not stat.S_ISREG(path_info.st_mode):
            fail(f"{label}/{relative} must be a regular file or directory")
        data = read_existing_file(path, max_bytes=max_bytes, label=f"{label}/{relative}")
        if data is None:
            fail(f"{label}/{relative} disappeared while snapshotting")
        final_info = stat_existing(path, f"{label}/{relative}")
        if final_info is None:
            fail(f"{label}/{relative} disappeared while snapshotting")
        if (
            final_info.st_dev,
            final_info.st_ino,
            final_info.st_size,
            final_info.st_mtime_ns,
            final_info.st_uid,
            final_info.st_nlink,
        ) != (
            path_info.st_dev,
            path_info.st_ino,
            path_info.st_size,
            path_info.st_mtime_ns,
            path_info.st_uid,
            path_info.st_nlink,
        ):
            fail(f"{label}/{relative} changed while snapshotting")
        entries[relative] = tree_entry_from_stat("file", path_info, data)
    return entries


def tree_matches_snapshot(
    root: Path, snapshot: dict[str, TreeEntry], *, max_bytes: int, label: str
) -> bool:
    return snapshot_tree(root, max_bytes=max_bytes, label=label) == snapshot


def cleanup_tombstone_name(target: Path, path: Path) -> str:
    try:
        relative = path.relative_to(control_tmp_dir(target))
    except ValueError:
        fail(f"cleanup tombstone is outside the fixed cleanup parent: {path}")
    if len(relative.parts) != 1:
        fail(f"cleanup tombstone must be a direct child of the fixed cleanup parent: {path}")
    name = relative.parts[0]
    if (
        not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or len(name.encode("utf-8")) > CLEANUP_MAX_ROOT_NAME_BYTES
    ):
        fail(f"cleanup tombstone name is invalid: {name}")
    if not any(name.startswith(prefix) for prefix in CLEANUP_TOMBSTONE_ROOT_PREFIXES):
        fail(f"cleanup tombstone is not machine-declared: {name}")
    return name


def cleanup_tombstone_path(target: Path, name: str) -> Path:
    if (
        not isinstance(name, str)
        or not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or len(name.encode("utf-8")) > CLEANUP_MAX_ROOT_NAME_BYTES
        or not any(name.startswith(prefix) for prefix in CLEANUP_TOMBSTONE_ROOT_PREFIXES)
    ):
        fail("cleanup tombstone name is invalid")
    return control_tmp_dir(target) / name


def cleanup_entry_payload(relative: str, entry: TreeEntry) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "path": relative,
        "kind": entry.kind,
        "mode": entry.mode,
        "uid": entry.uid,
        "nlink": entry.nlink,
        "size": entry.size,
        "dev": entry.dev,
        "ino": entry.ino,
        "mtime_ns": entry.mtime_ns,
        "sha256": sha256_bytes(entry.data) if entry.data is not None else None,
    }
    if set(payload) != {
        "path",
        "kind",
        "mode",
        "uid",
        "nlink",
        "size",
        "dev",
        "ino",
        "mtime_ns",
        "sha256",
    }:
        fail("cleanup journal entry schema is invalid")
    return payload


def cleanup_root_payload(target: Path, root: Path) -> dict[str, Any]:
    snapshot = snapshot_tree(root, max_bytes=SOFTWARE_MAX_BYTES, label="cleanup tombstone")
    return cleanup_root_payload_from_snapshot(target, root, snapshot)


def cleanup_root_payload_from_snapshot(
    target: Path, root: Path, snapshot: dict[str, TreeEntry]
) -> dict[str, Any]:
    name = cleanup_tombstone_name(target, root)
    if snapshot.get(".", absent_tree_entry()).kind == "absent":
        return {"name": name, "entries": []}
    if len(snapshot) > CLEANUP_MAX_ENTRIES:
        fail("cleanup tombstone exceeds the bounded entry limit")
    entries = [
        cleanup_entry_payload(relative, entry)
        for relative, entry in sorted(snapshot.items(), key=lambda item: item[0])
    ]
    return {"name": name, "entries": entries}


def cleanup_journal_payload_from_roots(
    target: Path, root_payloads: list[dict[str, Any]]
) -> dict[str, Any]:
    if len(root_payloads) > CLEANUP_MAX_ROOTS:
        fail("cleanup journal exceeds the bounded root limit")
    payload = {
        "schema_version": CLEANUP_JOURNAL_SCHEMA_VERSION,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "canonical_target": str(validate_target(target, create=False)),
        "cleanup_parent": CLEANUP_TOMBSTONE_PARENT_RELATIVE,
        "journal": CLEANUP_JOURNAL_RELATIVE,
        "roots": root_payloads,
    }
    if set(payload) != {
        "schema_version",
        "product_name",
        "build_version",
        "canonical_target",
        "cleanup_parent",
        "journal",
        "roots",
    }:
        fail("cleanup journal schema is invalid")
    cleanup_journal_canonical_bytes(payload)
    return payload


def cleanup_journal_payload(target: Path, roots: list[Path]) -> dict[str, Any]:
    unique_roots = list(dict.fromkeys(roots))
    root_payloads = [cleanup_root_payload(target, root) for root in unique_roots]
    return cleanup_journal_payload_from_roots(target, root_payloads)


def cleanup_journal_canonical_bytes(payload: dict[str, Any]) -> bytes:
    data = canonical_json(payload)
    if len(data) > CLEANUP_JOURNAL_MAX_BYTES:
        fail("cleanup journal exceeds the serialized byte limit")
    return data


def cleanup_existing_root_payloads(
    target: Path, *, replacement: tuple[str, dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    parent = control_tmp_dir(target)
    by_name: dict[str, dict[str, Any]] = {}
    if parent.exists() or parent.is_symlink():
        require_private_directory(parent, "cleanup tombstone parent")
        for root in sorted(parent.iterdir(), key=lambda item: item.name):
            name = cleanup_tombstone_name(target, root)
            by_name[name] = cleanup_root_payload(target, root)
    if replacement is not None:
        by_name[replacement[0]] = replacement[1]
    return [by_name[name] for name in sorted(by_name)]


def ensure_cleanup_journal_projected_root_fits(
    target: Path, root: Path, snapshot: dict[str, TreeEntry]
) -> None:
    payload = cleanup_root_payload_from_snapshot(target, root, snapshot)
    cleanup_journal_payload_from_roots(
        target, cleanup_existing_root_payloads(target, replacement=(payload["name"], payload))
    )


def ensure_cleanup_journal_projected_file_fits(
    target: Path,
    stage_root: Path,
    backup_path: Path,
    source_path: Path,
    snapshot: FileSnapshot,
) -> None:
    if snapshot.data is None:
        return
    source_info = stat_existing(source_path, "cleanup journal projected file")
    if source_info is None:
        fail("cleanup journal projected file disappeared")
    projected = dict(
        snapshot_tree(stage_root, max_bytes=SOFTWARE_MAX_BYTES, label="cleanup tombstone")
    )
    relative = backup_path.relative_to(stage_root).as_posix()
    if relative in projected:
        fail("cleanup journal projected file already exists")
    projected[relative] = tree_entry_from_stat("file", source_info, snapshot.data)
    ensure_cleanup_journal_projected_root_fits(target, stage_root, projected)


def ensure_cleanup_journal_projected_tree_fits(
    target: Path,
    stage_root: Path,
    backup_path: Path,
    snapshot: dict[str, TreeEntry],
) -> None:
    projected = dict(
        snapshot_tree(stage_root, max_bytes=SOFTWARE_MAX_BYTES, label="cleanup tombstone")
    )
    prefix = backup_path.relative_to(stage_root).as_posix()
    for relative, entry in snapshot.items():
        projected_relative = prefix if relative == "." else f"{prefix}/{relative}"
        if projected_relative in projected:
            fail("cleanup journal projected tree already exists")
        projected[projected_relative] = entry
    ensure_cleanup_journal_projected_root_fits(target, stage_root, projected)


def require_cleanup_scalar(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        fail(f"cleanup journal {label} is invalid")
    return value


def cleanup_entry_from_payload(entry: dict[str, Any]) -> TreeEntry:
    data = None
    if entry["kind"] == "file":
        if entry["sha256"] is None:
            fail("cleanup journal file digest is invalid")
    elif entry["sha256"] is not None:
        fail("cleanup journal non-file digest is invalid")
    return TreeEntry(
        entry["kind"],
        require_cleanup_scalar(entry["mode"], "mode"),
        data,
        require_cleanup_scalar(entry["size"], "size"),
        require_cleanup_scalar(entry["dev"], "dev"),
        require_cleanup_scalar(entry["ino"], "ino"),
        require_cleanup_scalar(entry["mtime_ns"], "mtime_ns"),
        require_cleanup_scalar(entry["uid"], "uid"),
        require_cleanup_scalar(entry["nlink"], "nlink"),
    )


def cleanup_entry_matches_payload(path: Path, entry: dict[str, Any], label: str) -> bool:
    info = stat_existing(path, label)
    if info is None:
        return False
    kind = entry["kind"]
    if kind == "dir":
        if not stat.S_ISDIR(info.st_mode):
            return False
    elif kind == "file":
        if not stat.S_ISREG(info.st_mode):
            return False
        if info.st_nlink != 1:
            return False
        data = read_existing_file(path, max_bytes=SOFTWARE_MAX_BYTES, label=label)
        if data is None or sha256_bytes(data) != entry["sha256"]:
            return False
    else:
        return False
    return (
        stat.S_IMODE(info.st_mode) == entry["mode"]
        and int(info.st_uid) == entry["uid"]
        and int(info.st_nlink) == entry["nlink"]
        and int(info.st_size) == entry["size"]
        and int(info.st_dev) == entry["dev"]
        and int(info.st_ino) == entry["ino"]
        and int(info.st_mtime_ns) == entry["mtime_ns"]
    )


def validate_cleanup_journal(target: Path, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        fail("cleanup journal must contain a JSON object")
    if set(payload) != {
        "schema_version",
        "product_name",
        "build_version",
        "canonical_target",
        "cleanup_parent",
        "journal",
        "roots",
    }:
        fail("cleanup journal has invalid keys")
    if payload["schema_version"] != CLEANUP_JOURNAL_SCHEMA_VERSION:
        fail("cleanup journal schema_version is invalid")
    if payload["product_name"] != PRODUCT_NAME or payload["build_version"] != VERSION:
        fail("cleanup journal product identity is invalid")
    if payload["canonical_target"] != str(validate_target(target, create=False)):
        fail("cleanup journal target does not match")
    if payload["cleanup_parent"] != CLEANUP_TOMBSTONE_PARENT_RELATIVE:
        fail("cleanup journal cleanup parent is invalid")
    if payload["journal"] != CLEANUP_JOURNAL_RELATIVE:
        fail("cleanup journal path is invalid")
    roots = payload["roots"]
    if not isinstance(roots, list) or len(roots) > CLEANUP_MAX_ROOTS:
        fail("cleanup journal roots are invalid")
    names: set[str] = set()
    for root in roots:
        if not isinstance(root, dict) or set(root) != {"name", "entries"}:
            fail("cleanup journal root entry is invalid")
        name = root["name"]
        cleanup_tombstone_path(target, name)
        if name in names:
            fail("cleanup journal root names must be unique")
        names.add(name)
        entries = root["entries"]
        if not isinstance(entries, list) or len(entries) > CLEANUP_MAX_ENTRIES:
            fail("cleanup journal root entries are invalid")
        entry_paths: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {
                "path",
                "kind",
                "mode",
                "uid",
                "nlink",
                "size",
                "dev",
                "ino",
                "mtime_ns",
                "sha256",
            }:
                fail("cleanup journal tree entry is invalid")
            if not isinstance(entry["path"], str) or entry["kind"] not in {
                "dir",
                "file",
            }:
                fail("cleanup journal tree entry path or kind is invalid")
            if (
                not entry["path"]
                or len(entry["path"].encode("utf-8")) > CLEANUP_MAX_RELATIVE_BYTES
                or Path(entry["path"]).is_absolute()
                or ".." in Path(entry["path"]).parts
            ):
                fail("cleanup journal tree entry path is invalid")
            if entry["path"] in entry_paths:
                fail("cleanup journal tree entry paths must be unique")
            entry_paths.add(entry["path"])
            cleanup_entry_from_payload(entry)
        if entries and entries[0]["path"] != ".":
            fail("cleanup journal root snapshot must include the root entry first")
    cleanup_journal_canonical_bytes(payload)
    return payload


def read_cleanup_journal_file(
    target: Path, *, allow_recoverable_publication_alias: bool = False
) -> dict[str, Any] | None:
    path = cleanup_journal_path(target)
    if not (path.exists() or path.is_symlink()):
        return None
    if allow_recoverable_publication_alias:
        flags = os.O_RDONLY
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            fail(f"cleanup journal open failed: {exc}")
        try:
            payload, _ = cleanup_journal_descriptor_payload(
                descriptor, path, target, allow_recoverable_alias=True
            )
            return payload
        finally:
            os.close(descriptor)
    payload = read_json_file(
        path,
        max_bytes=CLEANUP_JOURNAL_MAX_BYTES,
        label=CLEANUP_JOURNAL_NAME,
        expected_mode=OWNER_FILE_MODE,
    )
    return validate_cleanup_journal(target, payload)


def is_cleanup_journal_temporary_alias(path: Path, candidate: Path) -> bool:
    return is_anchor_temporary_alias(path, candidate)


def cleanup_journal_descriptor_payload(
    descriptor: int, path: Path, target: Path, *, allow_recoverable_alias: bool
) -> tuple[dict[str, Any], os.stat_result]:
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode):
        fail("cleanup journal must be a regular file")
    require_current_user_owner(info, "cleanup journal")
    if stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
        fail(f"cleanup journal must have mode {OWNER_FILE_MODE:04o}")
    if info.st_size > CLEANUP_JOURNAL_MAX_BYTES:
        fail("cleanup journal is too large")
    if info.st_nlink != 1 and not (allow_recoverable_alias and info.st_nlink == 2):
        fail("cleanup journal has an unknown hardlink count")
    current = path.lstat()
    if stat.S_ISLNK(current.st_mode) or (current.st_dev, current.st_ino) != (
        info.st_dev,
        info.st_ino,
    ):
        fail("cleanup journal path binding changed")
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(descriptor, 65536)
        if not chunk:
            break
        total += len(chunk)
        if total > CLEANUP_JOURNAL_MAX_BYTES:
            fail("cleanup journal is too large")
        chunks.append(chunk)
    data = b"".join(chunks)
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"cleanup journal is invalid JSON: {exc}")
    payload = validate_cleanup_journal(target, payload)
    if data != canonical_json(payload):
        fail("cleanup journal is not canonical")
    return payload, info


def recover_cleanup_journal_publication_alias(target: Path) -> None:
    path = cleanup_journal_path(target)
    if not (path.exists() or path.is_symlink()):
        return
    require_private_directory(cleanup_root_dir(target), "cleanup root")
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        fail(f"cleanup journal open failed: {exc}")
    try:
        _, opened = cleanup_journal_descriptor_payload(
            descriptor, path, target, allow_recoverable_alias=True
        )
        if opened.st_nlink == 1:
            return
        aliases = cleanup_journal_publication_aliases(target, opened)
        try:
            aliases[0].unlink()
        except OSError as exc:
            fail(f"cleanup journal publication alias cleanup failed: {exc}")
        fsync_directory(path.parent, "cleanup journal publication alias cleanup")
        cleanup_journal_descriptor_payload(descriptor, path, target, allow_recoverable_alias=False)
    finally:
        os.close(descriptor)


def cleanup_journal_publication_aliases(target: Path, opened: os.stat_result) -> list[Path]:
    path = cleanup_journal_path(target)
    aliases: list[Path] = []
    for candidate in sorted(cleanup_root_dir(target).iterdir(), key=lambda item: item.name):
        if candidate.name == CLEANUP_JOURNAL_NAME:
            continue
        if not is_cleanup_journal_temporary_alias(path, candidate):
            fail("cleanup root contains incomplete or unknown journal state")
        info = stat_existing(candidate, "cleanup journal publication alias")
        if info is None:
            continue
        if not stat.S_ISREG(info.st_mode):
            fail("cleanup journal publication alias must be a regular file")
        require_current_user_owner(info, "cleanup journal publication alias")
        if stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
            fail(f"cleanup journal publication alias must have mode {OWNER_FILE_MODE:04o}")
        if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
            fail("cleanup journal publication alias does not match the final journal")
        aliases.append(candidate)
    if opened.st_nlink == 2:
        if len(aliases) != 1:
            fail("cleanup journal must have exactly one recoverable publication alias")
    elif aliases:
        fail("cleanup root contains incomplete or unknown journal state")
    return aliases


def cleanup_namespace_journal_entries(target: Path) -> list[Path]:
    root = cleanup_root_dir(target)
    if not (root.exists() or root.is_symlink()):
        return []
    require_private_directory(root, "cleanup root")
    return sorted(root.iterdir(), key=lambda item: item.name)


def validate_cleanup_namespace(
    target: Path,
    journal: dict[str, Any] | None,
    *,
    allow_recoverable_publication_alias: bool = False,
) -> None:
    entries = cleanup_namespace_journal_entries(target)
    names = [entry.name for entry in entries]
    if journal is None:
        if names:
            fail("cleanup root contains incomplete or unknown journal state")
    else:
        path = cleanup_journal_path(target)
        info = stat_existing(path, CLEANUP_JOURNAL_NAME)
        if info is None:
            fail("cleanup journal disappeared while validating cleanup namespace")
        if not stat.S_ISREG(info.st_mode):
            fail("cleanup journal must be a regular file")
        if allow_recoverable_publication_alias:
            aliases = cleanup_journal_publication_aliases(target, info)
            expected_names = sorted([CLEANUP_JOURNAL_NAME, *(alias.name for alias in aliases)])
            if names != expected_names:
                fail("cleanup root contains incomplete or unknown journal state")
        elif names != [CLEANUP_JOURNAL_NAME]:
            fail("cleanup root contains incomplete or unknown journal state")
    declared = {root["name"] for root in journal["roots"]} if journal is not None else set()
    parent = control_tmp_dir(target)
    if not (parent.exists() or parent.is_symlink()):
        return
    require_private_directory(parent, "cleanup tombstone parent")
    for entry in sorted(parent.iterdir(), key=lambda item: item.name):
        if journal is None:
            fail("cleanup tombstone exists without a journal")
            continue
        if entry.name not in declared:
            fail("cleanup tombstone parent contains unknown state")


def validate_cleanup_tombstones(target: Path, journal: dict[str, Any]) -> None:
    for root in journal["roots"]:
        path = cleanup_tombstone_path(target, root["name"])
        if not (path.exists() or path.is_symlink()):
            continue
        declared = {entry["path"] for entry in root["entries"]}
        current = snapshot_tree(path, max_bytes=SOFTWARE_MAX_BYTES, label="cleanup tombstone")
        if not set(current).issubset(declared):
            fail("cleanup tombstone contains replaced or unknown state")
        entries_by_path = {entry["path"]: entry for entry in root["entries"]}
        for entry in root["entries"]:
            item_path = path if entry["path"] == "." else path / entry["path"]
            if not (item_path.exists() or item_path.is_symlink()):
                continue
            validate_cleanup_tombstone_entry_present(path, root, entry, entries_by_path)


def read_cleanup_journal(
    target: Path, *, allow_recoverable_publication_alias: bool = False
) -> dict[str, Any] | None:
    journal = read_cleanup_journal_file(
        target, allow_recoverable_publication_alias=allow_recoverable_publication_alias
    )
    validate_cleanup_namespace(
        target,
        journal,
        allow_recoverable_publication_alias=allow_recoverable_publication_alias,
    )
    if journal is not None:
        validate_cleanup_tombstones(target, journal)
    return journal


def cleanup_pending_metadata(
    target: Path, *, allow_recoverable_publication_alias: bool = False
) -> dict[str, Any]:
    base = {
        "cleanup_pending": False,
        "cleanup_pending_roots": 0,
        "cleanup_pending_entries": 0,
    }
    if not target.exists() and not target.is_symlink():
        return base
    require_private_directory(target, "target")
    journal = read_cleanup_journal(
        target, allow_recoverable_publication_alias=allow_recoverable_publication_alias
    )
    if journal is None:
        return base
    return {
        "cleanup_pending": True,
        "cleanup_pending_roots": len(journal["roots"]),
        "cleanup_pending_entries": sum(len(root["entries"]) for root in journal["roots"]),
    }


def cleanup_pending(target: Path) -> bool:
    return bool(cleanup_pending_metadata(target)["cleanup_pending"])


def require_valid_pending_cleanup_after_failure(target: Path) -> None:
    metadata = cleanup_pending_metadata(target, allow_recoverable_publication_alias=True)
    if not metadata["cleanup_pending"]:
        fail("cleanup journal is not pending after cleanup failure")


def post_commit_cleanup_failure(target: Path, cause: BaseException) -> bool:
    try:
        require_valid_pending_cleanup_after_failure(target)
    except BaseException as validation_error:
        raise PostCommitCleanupError(str(validation_error)) from cause
    return True


def retry_cleanup_step(label: str, action: Any) -> bool:
    for _attempt in range(ROLLBACK_MAX_ATTEMPTS):
        try:
            action()
            return True
        except BaseException:
            if _attempt == ROLLBACK_MAX_ATTEMPTS - 1:
                return False
    return False


def write_cleanup_journal(target: Path, roots: list[Path]) -> bool:
    if not roots:
        return True
    ensure_private_directory(managed_control_dir(target), "NDDev control root")
    payload = cleanup_journal_payload(target, roots)
    data = cleanup_journal_canonical_bytes(payload)
    path = cleanup_journal_path(target)
    if path.exists() or path.is_symlink():
        fail("cleanup journal is already pending")
    ensure_private_directory(cleanup_root_dir(target), "cleanup root")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, OWNER_FILE_MODE)
    try:
        offset = 0
        while offset < len(data):
            written = os.write(descriptor, data[offset:])
            if written <= 0:
                fail("cleanup journal write made no progress")
            offset += written
        os.fchmod(descriptor, OWNER_FILE_MODE)
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        cleanup_anchor_temporary(temporary, "cleanup journal")
        raise
    os.close(descriptor)
    try:
        os.link(temporary, path)
    except FileExistsError:
        cleanup_anchor_temporary(temporary, "cleanup journal")
        fail("cleanup journal is already pending")
    except OSError as exc:
        cleanup_anchor_temporary(temporary, "cleanup journal")
        fail(f"cleanup journal publication failed: {exc}")
    parent_synced = retry_cleanup_step(
        "cleanup journal publication",
        lambda: fsync_directory(path.parent, "cleanup journal publication"),
    )
    alias_removed = retry_cleanup_step(
        "cleanup journal publication alias",
        lambda: cleanup_anchor_temporary(temporary, "cleanup journal"),
    )
    alias_cleanup_synced = retry_cleanup_step(
        "cleanup journal temporary cleanup",
        lambda: fsync_directory(path.parent, "cleanup journal temporary cleanup"),
    )
    if not (parent_synced and alias_removed and alias_cleanup_synced):
        try:
            require_valid_pending_cleanup_after_failure(target)
        except GrokBuildSetupError as exc:
            raise PostCommitCleanupError(str(exc)) from exc
        return False
    try:
        read_cleanup_journal(target)
    except BaseException as exc:
        return post_commit_cleanup_failure(target, exc)
    return True


def cleanup_root_declared_paths(target: Path, root: dict[str, Any]) -> list[Path]:
    root_path = cleanup_tombstone_path(target, root["name"])
    paths: list[Path] = []
    for entry in root["entries"]:
        path = root_path if entry["path"] == "." else root_path / entry["path"]
        paths.append(path)
    return paths


def cleanup_declared_child_names(entries: list[dict[str, Any]]) -> dict[str, set[str]]:
    children: dict[str, set[str]] = {}
    for entry in entries:
        relative = Path(entry["path"])
        if entry["path"] == ".":
            continue
        parent = relative.parent.as_posix()
        if parent == "":
            parent = "."
        children.setdefault(parent, set()).add(relative.name)
    return children


def cleanup_remaining_child_names(
    root_path: Path, entries: list[dict[str, Any]]
) -> dict[str, set[str]]:
    remaining: dict[str, set[str]] = {}
    for entry in entries:
        path = root_path if entry["path"] == "." else root_path / entry["path"]
        if not (path.exists() or path.is_symlink()):
            continue
        relative = Path(entry["path"])
        if entry["path"] == ".":
            continue
        parent = relative.parent.as_posix()
        if parent == "":
            parent = "."
        remaining.setdefault(parent, set()).add(relative.name)
    return remaining


def validate_cleanup_directory_remaining_children(
    root_path: Path,
    entry: dict[str, Any],
    declared_children: dict[str, set[str]],
    remaining_children: dict[str, set[str]],
    label: str,
) -> None:
    path = root_path if entry["path"] == "." else root_path / entry["path"]
    info = stat_existing(path, label)
    if info is None:
        return
    actual = {child.name for child in path.iterdir()}
    expected_remaining = remaining_children.get(entry["path"], set())
    if actual != expected_remaining:
        fail("cleanup tombstone directory contains unknown or replaced children")
    if expected_remaining == declared_children.get(entry["path"], set()):
        if not cleanup_entry_matches_payload(path, entry, label):
            fail("cleanup tombstone directory metadata changed before deletion")
        return
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_IMODE(info.st_mode) != entry["mode"]
        or int(info.st_uid) != entry["uid"]
        or int(info.st_dev) != entry["dev"]
        or int(info.st_ino) != entry["ino"]
    ):
        fail("cleanup tombstone directory identity changed before deletion")


def validate_cleanup_tombstone_entry_present(
    root_path: Path,
    root: dict[str, Any],
    entry: dict[str, Any],
    entries_by_path: dict[str, dict[str, Any]],
) -> None:
    path = root_path if entry["path"] == "." else root_path / entry["path"]
    label = f"cleanup tombstone {root['name']}/{entry['path']}"
    if entry["kind"] == "file":
        if not cleanup_entry_matches_payload(path, entry, label):
            fail("cleanup tombstone identity does not match the journal")
        return
    declared_children = cleanup_declared_child_names(list(entries_by_path.values()))
    remaining_children = cleanup_remaining_child_names(root_path, list(entries_by_path.values()))
    validate_cleanup_directory_remaining_children(
        root_path,
        entry,
        declared_children,
        remaining_children,
        label,
    )


def drain_cleanup_journal(target: Path) -> None:
    recover_cleanup_journal_publication_alias(target)
    journal = read_cleanup_journal(target)
    if journal is None:
        return
    for root in journal["roots"]:
        root_path = cleanup_tombstone_path(target, root["name"])
        if not (root_path.exists() or root_path.is_symlink()):
            continue
        validate_cleanup_tombstones(target, {"roots": [root]})
        for entry in sorted(
            root["entries"], key=lambda item: len(Path(item["path"]).parts), reverse=True
        ):
            path = root_path if entry["path"] == "." else root_path / entry["path"]
            if not (path.exists() or path.is_symlink()):
                continue
            if entry["kind"] == "dir":
                declared_children = cleanup_declared_child_names(root["entries"])
                remaining_children = cleanup_remaining_child_names(root_path, root["entries"])
                validate_cleanup_directory_remaining_children(
                    root_path,
                    entry,
                    declared_children,
                    remaining_children,
                    f"cleanup tombstone {root['name']}/{entry['path']}",
                )
            elif not cleanup_entry_matches_payload(
                path, entry, f"cleanup tombstone {root['name']}/{entry['path']}"
            ):
                fail("cleanup tombstone identity changed before deletion")
            if entry["kind"] == "file":
                durable_unlink(path, f"cleanup tombstone {root['name']}/{entry['path']}")
            elif entry["kind"] == "dir":
                durable_rmdir(path, f"cleanup tombstone {root['name']}/{entry['path']}")
            fsync_directory(control_tmp_dir(target), "cleanup tombstone parent")
        if root_path.exists() or root_path.is_symlink():
            fail("cleanup tombstone root still exists after drain")
    durable_unlink(cleanup_journal_path(target), CLEANUP_JOURNAL_NAME)
    remove_empty_directory_if_created(cleanup_root_dir(target), existed_before=False)
    remove_empty_directory_if_created(control_tmp_dir(target), existed_before=False)


def collect_cleanup_roots(
    target: Path,
    *,
    preserved_files: dict[str, PreservedFile],
    preserved_trees: dict[str, PreservedTree] | None = None,
    extra_roots: list[Path] | tuple[Path, ...] | None = None,
) -> list[Path]:
    roots: list[Path] = []
    roots.extend(entry.stage_root for entry in preserved_files.values())
    if preserved_trees is not None:
        roots.extend(
            entry.stage_root for entry in preserved_trees.values() if entry.stage_root is not None
        )
    roots.extend(extra_roots or ())
    return [
        root
        for root in dict.fromkeys(roots)
        if root.exists() or root.is_symlink()
        if cleanup_tombstone_name(target, root)
    ]


def finish_journaled_cleanup(target: Path, roots: list[Path], cleanup: Any) -> bool:
    roots = list(dict.fromkeys(roots))
    if not roots:
        cleanup()
        return False
    if not write_cleanup_journal(target, roots):
        return True
    try:
        drain_cleanup_journal(target)
        return False
    except BaseException as exc:
        return post_commit_cleanup_failure(target, exc)


def snapshot_directory_entry(path: Path, label: str) -> TreeEntry:
    info = stat_existing(path, label)
    if info is None:
        return absent_tree_entry()
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    require_current_user_owner(info, label)
    return tree_entry_from_stat("dir", info, None)


def directory_entry_matches(path: Path, entry: TreeEntry, label: str) -> bool:
    info = stat_existing(path, label)
    if entry.kind == "absent":
        return info is None
    if info is None or not stat.S_ISDIR(info.st_mode):
        return False
    require_current_user_owner(info, label)
    return (
        stat.S_IMODE(info.st_mode) == entry.mode
        and int(info.st_size) == entry.size
        and int(info.st_dev) == entry.dev
        and int(info.st_ino) == entry.ino
        and int(info.st_mtime_ns) == entry.mtime_ns
        and int(info.st_uid) == entry.uid
        and int(info.st_nlink) == entry.nlink
    )


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
        fail(f"{label} exact directory object is missing")
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    require_current_user_owner(info, label)
    if entry.dev is not None and info.st_dev != entry.dev:
        fail(f"{label} directory device changed")
    if entry.ino is not None and info.st_ino != entry.ino:
        fail(f"{label} directory inode changed")
    if stat.S_IMODE(info.st_mode) != entry.mode:
        path.chmod(entry.mode)
        fsync_directory(path, label)
    restore_tree_entry_mtime(path, entry, label)


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


def remove_tree_until_absent_retry(root: Path, *, max_bytes: int, label: str) -> None:
    retry_until_exact(
        label,
        lambda: not (root.exists() or root.is_symlink()),
        lambda: remove_tree_once(root, max_bytes=max_bytes, label=label),
    )


def fsync_file(path: Path, label: str) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        fail(f"{label} fsync open failed: {exc}")
    try:
        os.fsync(descriptor)
    except OSError as exc:
        fail(f"{label} fsync failed: {exc}")
    finally:
        os.close(descriptor)


def restore_tree_entry_mtime(path: Path, entry: TreeEntry, label: str) -> None:
    if entry.mtime_ns is None:
        return
    info = path.lstat()
    if info.st_mtime_ns == entry.mtime_ns:
        return
    os.utime(
        path,
        ns=(int(info.st_atime_ns), int(entry.mtime_ns)),
        follow_symlinks=False,
    )
    if stat.S_ISDIR(info.st_mode):
        fsync_directory(path, f"{label} mtime restore")
    else:
        fsync_file(path, f"{label} mtime restore")


def require_same_tree_object(path: Path, entry: TreeEntry, label: str) -> os.stat_result:
    info = stat_existing(path, label)
    if info is None:
        fail(f"{label} exact tree object is missing")
    if entry.dev is not None and info.st_dev != entry.dev:
        fail(f"{label} device changed")
    if entry.ino is not None and info.st_ino != entry.ino:
        fail(f"{label} inode changed")
    if entry.uid is not None and info.st_uid != entry.uid:
        fail(f"{label} owner changed")
    if entry.nlink is not None and info.st_nlink != entry.nlink:
        fail(f"{label} link count changed")
    return info


def restore_tree_directory_entry(path: Path, entry: TreeEntry, label: str) -> None:
    if entry.kind != "dir" or entry.mode is None:
        fail(f"{label} directory snapshot is invalid")
    info = require_same_tree_object(path, entry, label)
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    require_current_user_owner(info, label)
    if stat.S_IMODE(info.st_mode) != entry.mode:
        path.chmod(entry.mode)
        fsync_directory(path, label)
    restore_tree_entry_mtime(path, entry, label)


def restore_tree_file_entry(path: Path, entry: TreeEntry, *, max_bytes: int, label: str) -> None:
    if entry.kind != "file" or entry.mode is None or entry.data is None:
        fail(f"{label} file snapshot is invalid")
    info = require_same_tree_object(path, entry, label)
    if not stat.S_ISREG(info.st_mode):
        fail(f"{label} must be a regular file")
    require_current_user_owner(info, label)
    if info.st_nlink != 1:
        fail(f"{label} must not be a hardlink")
    if entry.size is not None and len(entry.data) != entry.size:
        fail(f"{label} snapshot size does not match bytes")
    current_data = read_existing_file(path, max_bytes=max_bytes, label=label)
    if current_data != entry.data:
        flags = os.O_WRONLY
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            fail(f"{label} exact file restore open failed: {exc}")
        try:
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) != (entry.dev, entry.ino):
                fail(f"{label} inode changed while restoring")
            os.ftruncate(descriptor, 0)
            offset = 0
            while offset < len(entry.data):
                written = os.write(descriptor, entry.data[offset:])
                if written <= 0:
                    fail(f"{label} exact file restore made no progress")
                offset += written
            os.fchmod(descriptor, entry.mode)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    info = require_same_tree_object(path, entry, label)
    if stat.S_IMODE(info.st_mode) != entry.mode:
        path.chmod(entry.mode)
        fsync_file(path, label)
    restore_tree_entry_mtime(path, entry, label)


def restore_tree_once(
    root: Path, snapshot: dict[str, TreeEntry], *, max_bytes: int, label: str
) -> None:
    root_entry = snapshot.get(".")
    if root_entry is None:
        fail(f"{label} snapshot is missing the root entry")
    if root_entry.kind == "absent":
        remove_tree_until_absent_retry(root, max_bytes=max_bytes, label=label)
        return
    if root_entry.kind != "dir" or root_entry.mode is None:
        fail(f"{label} snapshot root is invalid")
    restore_tree_directory_entry(root, root_entry, label)
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
    for relative, entry in sorted(snapshot.items()):
        if entry.kind != "file":
            continue
        restore_tree_file_entry(
            tree_path(root, relative),
            entry,
            max_bytes=max_bytes,
            label=f"{label}/{relative}",
        )
    for relative, entry in sorted(
        snapshot.items(), key=lambda item: len(Path(item[0]).parts), reverse=True
    ):
        if entry.kind != "dir":
            continue
        restore_tree_directory_entry(tree_path(root, relative), entry, f"{label}/{relative}")


def restore_tree_retry(
    root: Path, snapshot: dict[str, TreeEntry], *, max_bytes: int, label: str
) -> None:
    retry_until_exact(
        label,
        lambda: tree_matches_snapshot(root, snapshot, max_bytes=max_bytes, label=label),
        lambda: restore_tree_once(root, snapshot, max_bytes=max_bytes, label=label),
    )


def snapshot_lifecycle_state(
    target: Path,
    extra_paths: tuple[str, ...] | list[str] | None = None,
    preserve_paths: tuple[str, ...] | list[str] | None = None,
) -> LifecycleSnapshot:
    control_root_snapshot = snapshot_directory_entry(
        managed_control_dir(target), "NDDev control root"
    )
    cleanup_root_snapshot = snapshot_directory_entry(cleanup_root_dir(target), "cleanup root")
    backup_pool_snapshot = snapshot_tree(
        backup_pool(target), max_bytes=METADATA_MAX_BYTES, label="backup pool"
    )
    control_tmp_snapshot = snapshot_tree(
        control_tmp_dir(target), max_bytes=METADATA_MAX_BYTES, label="control tmp"
    )
    lock_parent_snapshot = snapshot_tree(
        lock_parent_dir(target), max_bytes=METADATA_MAX_BYTES, label="target lock parent"
    )
    launch_images_snapshot = snapshot_tree(
        launch_image_dir(target), max_bytes=SOFTWARE_MAX_BYTES, label="launch images"
    )
    files_snapshot = snapshot_files(target, extra_paths=extra_paths)
    preserved = preserve_managed_files(
        target,
        tuple(preserve_paths or ()),
        label="managed lifecycle rollback",
    )
    return LifecycleSnapshot(
        files=files_snapshot,
        control_root_dir=control_root_snapshot,
        cleanup_root_dir=cleanup_root_snapshot,
        backup_pool=backup_pool_snapshot,
        control_tmp=control_tmp_snapshot,
        lock_parent=lock_parent_snapshot,
        launch_images=launch_images_snapshot,
        preserved_files=preserved,
    )


def lifecycle_matches_snapshot(target: Path, snapshot: LifecycleSnapshot) -> bool:
    return (
        managed_files_match_snapshot(target, snapshot.files)
        and directory_entry_matches(
            managed_control_dir(target), snapshot.control_root_dir, "NDDev control root"
        )
        and directory_entry_matches(
            cleanup_root_dir(target), snapshot.cleanup_root_dir, "cleanup root"
        )
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
            lock_parent_dir(target),
            snapshot.lock_parent,
            max_bytes=METADATA_MAX_BYTES,
            label="target lock parent",
        )
        and tree_matches_snapshot(
            launch_image_dir(target),
            snapshot.launch_images,
            max_bytes=SOFTWARE_MAX_BYTES,
            label="launch images",
        )
    )


def restore_lifecycle_snapshot_once(target: Path, snapshot: LifecycleSnapshot) -> None:
    restore_preserved_files_retry(snapshot.preserved_files)
    restore_snapshot(target, snapshot.files)
    ensure_directory_entry(cleanup_root_dir(target), snapshot.cleanup_root_dir, "cleanup root")
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
        lock_parent_dir(target),
        snapshot.lock_parent,
        max_bytes=METADATA_MAX_BYTES,
        label="target lock parent",
    )
    restore_tree_retry(
        launch_image_dir(target),
        snapshot.launch_images,
        max_bytes=SOFTWARE_MAX_BYTES,
        label="launch images",
    )
    ensure_directory_entry(
        managed_control_dir(target), snapshot.control_root_dir, "NDDev control root"
    )


def restore_lifecycle_snapshot_retry(target: Path, snapshot: LifecycleSnapshot) -> None:
    restore_lifecycle_snapshot_once(target, snapshot)
    retry_until_exact(
        "managed lifecycle rollback",
        lambda: lifecycle_matches_snapshot(target, snapshot),
        lambda: restore_lifecycle_snapshot_once(target, snapshot),
    )
    cleanup_preserved_stage_roots_retry(snapshot.preserved_files)


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
    ensure_private_directory(managed_control_dir(target), "NDDev control root")
    slot = choose_backup_slot(backup_pool(target))
    envelope = build_backup_envelope(target, stamp, slot)
    require_control_directory(managed_control_dir(target), "NDDev control root", allow_locked=False)
    ensure_private_directory(control_tmp_dir(target), "NDDev control tmp")
    stage_root = control_tmp_dir(target) / f"backup.{slot}.{os.getpid()}.{time.time_ns()}"
    ensure_private_directory(stage_root, "backup stage root")
    stage_path = stage_root / BACKUP_NAME
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
    return BackupTransaction(
        slot=slot, stage_root=stage_root, stage_path=stage_path, envelope=envelope
    )


def cleanup_backup_transaction_stage(transaction: BackupTransaction) -> None:
    remove_tree_until_absent_retry(
        transaction.stage_root, max_bytes=METADATA_MAX_BYTES, label="backup stage cleanup"
    )


def commit_backup_transaction(target: Path, transaction: BackupTransaction | None) -> BackupCommit:
    if transaction is None:
        return BackupCommit(None, {}, [])
    pool = backup_pool(target)
    require_control_directory(pool.parent, "NDDev control root", allow_locked=False)
    ensure_private_directory(pool, "backup pool")
    slot_dir = pool / str(transaction.slot)
    ensure_private_directory(slot_dir, "backup slot")
    envelope_path = slot_dir / BACKUP_NAME
    expected = canonical_json(transaction.envelope)
    target_entry = snapshot_directory_entry(target, "target")
    stage_root = preservation_stage_root(target, "backup slot rollback")
    preserved = {
        BACKUP_NAME: preserve_file_for_rollback(
            target,
            envelope_path,
            label=BACKUP_NAME,
            max_bytes=METADATA_MAX_BYTES,
            reader=read_existing_file,
            stage_root=stage_root,
            expected_mode=OWNER_FILE_MODE,
            target_entry=target_entry,
        )
    }
    try:
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
        return BackupCommit(
            transaction.slot,
            preserved,
            collect_cleanup_roots(
                target,
                preserved_files=preserved,
                extra_roots=[transaction.stage_root],
            ),
        )
    except BaseException:
        restore_preserved_files_retry(preserved)
        cleanup_preserved_stage_roots_retry(preserved)
        cleanup_backup_transaction_stage(transaction)
        raise


def rollback_backup_transaction(target: Path, transaction: BackupTransaction | None) -> None:
    del target
    if transaction is not None:
        cleanup_backup_transaction_stage(transaction)


def create_backup(target: Path, stamp: dict[str, Any]) -> int:
    transaction = begin_backup_transaction(target, stamp)
    commit = commit_backup_transaction(target, transaction)
    if commit.slot is None:
        fail("backup transaction did not commit")
    finish_journaled_cleanup(
        target,
        commit.cleanup_roots,
        lambda: (
            cleanup_backup_transaction_stage(transaction),
            cleanup_preserved_stage_roots_retry(commit.preserved_files),
        ),
    )
    return commit.slot


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


def remove_managed_path(
    target: Path, relative: str, preserved_files: dict[str, PreservedFile] | None = None
) -> None:
    path = safe_target_path(target, relative)
    if relative in MERGED_MARKER_PATHS:
        preserved = preserved_files.get(relative) if preserved_files is not None else None
        remove_managed_block_from_target(
            target,
            relative,
            source_data=preserved.snapshot.data if preserved is not None else None,
        )
    else:
        if path.exists() or path.is_symlink():
            durable_unlink(path, relative)


def write_setup(
    target: Path,
    setup: dict[str, Any],
    profile: dict[str, Any],
    *,
    require_existing: bool = False,
) -> dict[str, Any]:
    require_supported_runtime_platform()
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
        if current is not None and current == desired_stamp and not changed and not removed:
            return {
                "setup_id": setup["id"],
                "profile_id": profile["id"],
                "changed": [],
                "removed": [],
                "backup_slot": None,
                "cleanup_pending": False,
                "target": str(validate_target(target, create=False)),
            }
        snapshot = snapshot_lifecycle_state(
            target,
            extra_paths=sorted(current["managed_files"]) if current is not None else None,
        )
        cleanup_pending_result = False
        backup_commit = BackupCommit(None, {}, [])
        try:
            backup_transaction = None
            if current is not None and (
                current["setup_id"] != setup["id"] or current["profile_id"] != profile["id"]
            ):
                backup_transaction = begin_backup_transaction(target, current)
            snapshot = snapshot._replace(
                preserved_files=preserve_managed_files(
                    target,
                    sorted({*changed, *removed, STAMP_NAME}),
                    label="managed lifecycle rollback",
                )
            )
            for relative in removed:
                remove_managed_path(target, relative, snapshot.preserved_files)
            for relative in changed:
                data = files[relative]
                atomic_write(safe_target_path(target, relative), data, target)
            atomic_write(stamp_path(target), canonical_json(desired_stamp), target)
            prune_empty_managed_dirs(target)
            validate_intended_setup_state(target, desired_stamp, files)
            backup_commit = commit_backup_transaction(target, backup_transaction)
            cleanup_pending_result = finish_journaled_cleanup(
                target,
                collect_cleanup_roots(
                    target,
                    preserved_files=snapshot.preserved_files,
                    extra_roots=backup_commit.cleanup_roots,
                ),
                lambda: (
                    cleanup_preserved_stage_roots_retry(snapshot.preserved_files),
                    cleanup_preserved_stage_roots_retry(backup_commit.preserved_files),
                    cleanup_backup_transaction_stage(backup_transaction)
                    if backup_transaction is not None
                    else None,
                ),
            )
        except PostCommitCleanupError:
            raise
        except BaseException:
            restore_preserved_files_retry(backup_commit.preserved_files)
            restore_lifecycle_snapshot_retry(target, snapshot)
            raise
        return {
            "setup_id": setup["id"],
            "profile_id": profile["id"],
            "changed": changed,
            "removed": removed,
            "backup_slot": backup_commit.slot,
            "cleanup_pending": cleanup_pending_result,
            "target": str(validate_target(target, create=False)),
        }


def update_setup(target: Path) -> dict[str, Any]:
    require_supported_runtime_platform()
    with target_lock(target, create=False) as target:
        current = read_stamp(target)
        if current is None:
            fail("update requires an already managed target")
        if is_legacy_stamp(current):
            fail("target uses legacy managed state; run migrate, restore, or remove")
        drift = drift_for_stamp(target, current)
        if drift:
            fail(f"managed target has drift: {', '.join(drift)}")
        setup = load_setup(current["setup_id"])
        profile = load_profile(current["profile_id"])
        files = desired_files(target, setup, profile)
        desired_stamp = build_stamp(target, setup["id"], profile["id"], files)
        changed = changed_paths_for_desired_files(target, current, files)
        removed = removed_paths_for_stamp_replacement(current, files)
        if current == desired_stamp and not changed and not removed:
            return {
                "setup_id": setup["id"],
                "profile_id": profile["id"],
                "operation": "current",
                "changed": [],
                "removed": [],
                "backup_slot": None,
                "cleanup_pending": False,
                "target": str(validate_target(target, create=False)),
            }
        snapshot = snapshot_lifecycle_state(
            target,
            extra_paths=sorted(current["managed_files"]),
            preserve_paths=sorted({*changed, *removed, STAMP_NAME}),
        )
        cleanup_pending_result = False
        try:
            for relative in removed:
                remove_managed_path(target, relative, snapshot.preserved_files)
            for relative in changed:
                atomic_write(safe_target_path(target, relative), files[relative], target)
            atomic_write(stamp_path(target), canonical_json(desired_stamp), target)
            prune_empty_managed_dirs(target)
            validate_intended_setup_state(target, desired_stamp, files)
            cleanup_pending_result = finish_journaled_cleanup(
                target,
                collect_cleanup_roots(target, preserved_files=snapshot.preserved_files),
                lambda: cleanup_preserved_stage_roots_retry(snapshot.preserved_files),
            )
        except PostCommitCleanupError:
            raise
        except BaseException:
            restore_lifecycle_snapshot_retry(target, snapshot)
            raise
        return {
            "setup_id": setup["id"],
            "profile_id": profile["id"],
            "operation": "update",
            "changed": changed,
            "removed": removed,
            "backup_slot": None,
            "cleanup_pending": cleanup_pending_result,
            "target": str(validate_target(target, create=False)),
        }


def migrate_setup(
    target: Path,
    setup: dict[str, Any],
    requested_profile_id: str | None,
) -> dict[str, Any]:
    require_supported_runtime_platform()
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
        snapshot = snapshot_lifecycle_state(
            target,
            extra_paths=sorted(current["managed_files"]),
        )
        cleanup_pending_result = False
        backup_commit = BackupCommit(None, {}, [])
        try:
            backup_transaction = begin_backup_transaction(target, current)
            snapshot = snapshot._replace(
                preserved_files=preserve_managed_files(
                    target,
                    sorted({*changed, *removed, STAMP_NAME}),
                    label="managed lifecycle rollback",
                )
            )
            for relative in removed:
                remove_managed_path(target, relative, snapshot.preserved_files)
            for relative in changed:
                atomic_write(safe_target_path(target, relative), files[relative], target)
            atomic_write(stamp_path(target), canonical_json(desired_stamp), target)
            prune_empty_managed_dirs(target)
            validate_intended_setup_state(target, desired_stamp, files)
            backup_commit = commit_backup_transaction(target, backup_transaction)
            cleanup_pending_result = finish_journaled_cleanup(
                target,
                collect_cleanup_roots(
                    target,
                    preserved_files=snapshot.preserved_files,
                    extra_roots=backup_commit.cleanup_roots,
                ),
                lambda: (
                    cleanup_preserved_stage_roots_retry(snapshot.preserved_files),
                    cleanup_preserved_stage_roots_retry(backup_commit.preserved_files),
                    cleanup_backup_transaction_stage(backup_transaction),
                ),
            )
        except PostCommitCleanupError:
            raise
        except BaseException:
            restore_preserved_files_retry(backup_commit.preserved_files)
            restore_lifecycle_snapshot_retry(target, snapshot)
            raise
        return {
            "setup_id": setup["id"],
            "profile_id": profile["id"],
            "source_legacy_setup_id": current["setup_id"],
            "changed": changed,
            "removed": removed,
            "backup_slot": backup_commit.slot,
            "cleanup_pending": cleanup_pending_result,
            "target": str(validate_target(target, create=False)),
        }


def restore_backup(target: Path, slot: int) -> dict[str, Any]:
    require_supported_runtime_platform()
    if slot < 0 or slot > 9:
        fail("backup slot must be between 0 and 9")
    with target_lock(target, create=False) as target:
        envelope_path = backup_envelope_path(target, slot)
        validate_backup_slot_topology(envelope_path, "backup")
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
        snapshot = snapshot_lifecycle_state(
            target,
            extra_paths=sorted(files),
            preserve_paths=sorted(files),
        )
        cleanup_pending_result = False
        try:
            for relative, data in sorted(files.items()):
                path = safe_target_path(target, relative)
                atomic_write(path, data, target)
            prune_empty_managed_dirs(target)
            restored_stamp = validate_restored_backup_state(target, expected_stamp, files)
            cleanup_pending_result = finish_journaled_cleanup(
                target,
                collect_cleanup_roots(target, preserved_files=snapshot.preserved_files),
                lambda: cleanup_preserved_stage_roots_retry(snapshot.preserved_files),
            )
        except PostCommitCleanupError:
            raise
        except BaseException:
            restore_lifecycle_snapshot_retry(target, snapshot)
            raise
        return {
            "setup_id": restored_stamp["setup_id"],
            "profile_id": restored_stamp.get("profile_id"),
            "legacy": is_legacy_stamp(restored_stamp),
            "backup_slot": slot,
            "cleanup_pending": cleanup_pending_result,
            "target": str(validate_target(target, create=False)),
        }


def remove_setup(target: Path) -> dict[str, Any]:
    require_supported_runtime_platform()
    with target_lock(target, create=False, allow_missing=True) as target:
        if not target.exists() and not target.is_symlink():
            return {
                "removed_setup_id": None,
                "changed": [],
                "removed": [],
                "cleanup_pending": False,
                "target": str(validate_target(target, create=False)),
            }
        stamp = read_stamp(target)
        if stamp is None:
            return {
                "removed_setup_id": None,
                "changed": [],
                "removed": [],
                "cleanup_pending": False,
                "target": str(validate_target(target, create=False)),
            }
        drift = drift_for_stamp(target, stamp)
        if drift:
            fail(f"managed target has drift: {', '.join(drift)}")
        removed_setup_id = stamp["setup_id"]
        removed_profile_id = stamp.get("profile_id")
        removed = sorted(stamp["managed_files"])
        snapshot = snapshot_lifecycle_state(
            target,
            extra_paths=sorted(stamp["managed_files"]),
            preserve_paths=sorted({*stamp["managed_files"], STAMP_NAME}),
        )
        cleanup_pending_result = False
        try:
            for relative in removed:
                remove_managed_path(target, relative, snapshot.preserved_files)
            durable_unlink(stamp_path(target), STAMP_NAME)
            prune_empty_managed_dirs(target)
            validate_removed_setup_state(target, removed)
            cleanup_pending_result = finish_journaled_cleanup(
                target,
                collect_cleanup_roots(target, preserved_files=snapshot.preserved_files),
                lambda: cleanup_preserved_stage_roots_retry(snapshot.preserved_files),
            )
        except PostCommitCleanupError:
            raise
        except BaseException:
            restore_lifecycle_snapshot_retry(target, snapshot)
            raise
        return {
            "removed_setup_id": removed_setup_id,
            "removed_profile_id": removed_profile_id,
            "removed_legacy": is_legacy_stamp(stamp),
            "changed": removed,
            "removed": removed,
            "cleanup_pending": cleanup_pending_result,
            "target": str(validate_target(target, create=False)),
        }


def remove_managed_block_from_target(
    target: Path, relative: str, *, source_data: bytes | None = None
) -> None:
    path = safe_target_path(target, relative)
    data = (
        source_data
        if source_data is not None
        else read_existing_file(path, max_bytes=MANAGED_MAX_BYTES, label=relative)
    )
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
    ensure_private_directory(managed_control_dir(target), "NDDev control root")
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
        require_lockable_directory(
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
        return FileSnapshot(None, None, None, None, None)
    data = read_software_file(path, label)
    info = require_software_regular_file(path, label)
    return FileSnapshot(
        data,
        stat.S_IMODE(info.st_mode),
        int(info.st_mtime_ns),
        int(info.st_dev),
        int(info.st_ino),
    )


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


def software_relative_path(target: Path, path: Path) -> str:
    return path.relative_to(target).as_posix()


def preserve_software_files(
    target: Path,
    paths: tuple[Path, ...] | list[Path],
    *,
    label: str,
    target_entry: TreeEntry | None = None,
) -> dict[str, PreservedFile]:
    unique = tuple(dict.fromkeys(paths))
    if not unique:
        return {}
    if target_entry is None:
        target_entry = snapshot_directory_entry(target, "target")
    stage_root = preservation_stage_root(target, label)
    preserved: dict[str, PreservedFile] = {}
    intent_entries: dict[str, PreservedFile | PreservedTree] = {}
    for path in unique:
        relative = software_relative_path(target, path)
        preserved[relative] = preserve_file_for_rollback(
            target,
            path,
            label=relative,
            max_bytes=SOFTWARE_MAX_BYTES,
            reader=read_optional_software_file_for_atomic,
            stage_root=stage_root,
            intent_entries=intent_entries,
            target_entry=target_entry,
        )
    return preserved


def snapshot_software_state(
    target: Path,
    preserve_paths: tuple[Path, ...] | list[Path] | None = None,
    preserve_trees: tuple[Path, ...] | list[Path] | None = None,
) -> SoftwareSnapshot:
    target_entry = snapshot_directory_entry(target, "target")
    control_root_snapshot = snapshot_directory_entry(
        managed_control_dir(target), "NDDev control root"
    )
    cleanup_root_snapshot = snapshot_directory_entry(cleanup_root_dir(target), "cleanup root")
    software_root_snapshot = snapshot_tree(
        software_root(target), max_bytes=SOFTWARE_MAX_BYTES, label="software root"
    )
    software_container_snapshot = snapshot_directory_entry(
        software_container(target), ".nddev-software"
    )
    managed_binary_snapshot = snapshot_optional_software_file(managed_grok_path(target), "bin/grok")
    managed_bin_dir_snapshot = snapshot_directory_entry(managed_grok_path(target).parent, "bin")
    control_tmp_snapshot = snapshot_tree(
        control_tmp_dir(target), max_bytes=SOFTWARE_MAX_BYTES, label="control tmp"
    )
    lock_parent_snapshot = snapshot_tree(
        lock_parent_dir(target), max_bytes=METADATA_MAX_BYTES, label="target lock parent"
    )
    preserved = preserve_software_files(
        target,
        tuple(preserve_paths or ()),
        label="software rollback",
        target_entry=target_entry,
    )
    preserved_trees: dict[str, PreservedTree] = {}
    for path in tuple(dict.fromkeys(preserve_trees or ())):
        relative = software_relative_path(target, path)
        preserved_trees[relative] = preserve_tree_for_rollback(
            target,
            path,
            label=relative,
            max_bytes=SOFTWARE_MAX_BYTES,
            target_entry=target_entry,
        )
    return SoftwareSnapshot(
        control_root_dir=control_root_snapshot,
        cleanup_root_dir=cleanup_root_snapshot,
        software_root=software_root_snapshot,
        software_container_dir=software_container_snapshot,
        managed_binary=managed_binary_snapshot,
        managed_bin_dir=managed_bin_dir_snapshot,
        control_tmp=control_tmp_snapshot,
        lock_parent=lock_parent_snapshot,
        preserved_files=preserved,
        preserved_trees=preserved_trees,
    )


def software_matches_snapshot(target: Path, snapshot: SoftwareSnapshot) -> bool:
    return (
        directory_entry_matches(
            managed_control_dir(target), snapshot.control_root_dir, "NDDev control root"
        )
        and directory_entry_matches(
            cleanup_root_dir(target), snapshot.cleanup_root_dir, "cleanup root"
        )
        and tree_matches_snapshot(
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
        and tree_matches_snapshot(
            lock_parent_dir(target),
            snapshot.lock_parent,
            max_bytes=METADATA_MAX_BYTES,
            label="target lock parent",
        )
    )


def restore_software_snapshot_once(target: Path, snapshot: SoftwareSnapshot) -> None:
    restore_preserved_trees_retry(snapshot.preserved_trees)
    restore_preserved_files_retry(snapshot.preserved_files)
    ensure_directory_entry(cleanup_root_dir(target), snapshot.cleanup_root_dir, "cleanup root")
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
    restore_tree_retry(
        lock_parent_dir(target),
        snapshot.lock_parent,
        max_bytes=METADATA_MAX_BYTES,
        label="target lock parent",
    )
    ensure_directory_entry(
        managed_control_dir(target), snapshot.control_root_dir, "NDDev control root"
    )


def restore_software_snapshot_retry(target: Path, snapshot: SoftwareSnapshot) -> None:
    restore_software_snapshot_once(target, snapshot)
    retry_until_exact(
        "software rollback",
        lambda: software_matches_snapshot(target, snapshot),
        lambda: restore_software_snapshot_once(target, snapshot),
    )
    cleanup_preserved_stage_roots_retry(snapshot.preserved_files)
    cleanup_preserved_tree_stage_roots_retry(snapshot.preserved_trees)


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
    final_status = software_status_locked(target, validate_cleanup=False)
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
    return read_pinned_https_bytes(
        source, max_bytes=max_bytes, label="official Grok Build installer"
    )


def read_pinned_https_bytes(source: str, *, max_bytes: int, label: str) -> bytes:
    request = urllib.request.Request(source, headers={"User-Agent": f"{PRODUCT_NAME}/{VERSION}"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            expected_length_header = response.headers.get("Content-Length")
            expected_length = None
            if expected_length_header is not None:
                try:
                    expected_length = int(expected_length_header)
                except (TypeError, ValueError) as exc:
                    fail(f"{label} Content-Length is invalid: {exc}")
                if expected_length < 0:
                    fail(f"{label} Content-Length is invalid")
                if expected_length > max_bytes:
                    fail(f"{label} exceeds bounded read limit")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    fail(f"{label} exceeds bounded read limit")
                chunks.append(chunk)
    except GrokBuildSetupError:
        raise
    except (http.client.HTTPException, OSError, TimeoutError, urllib.error.URLError) as exc:
        fail(f"{label} fetch failed: {exc}")
    content = b"".join(chunks)
    if expected_length is not None and expected_length != len(content):
        fail(f"{label} length changed while reading")
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


def verify_npm_dist_payload(data: bytes, pin: dict[str, Any], label: str) -> str:
    integrity = str(pin["integrity"])
    algorithm, separator, digest_text = integrity.partition("-")
    if separator != "-" or algorithm != "sha512":
        fail(f"{label} npm integrity must be sha512")
    try:
        expected = base64.b64decode(digest_text.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError) as exc:
        fail(f"{label} npm integrity is invalid: {exc}")
    if hashlib.sha512(data).digest() != expected:
        fail(f"{label} npm integrity mismatch")
    shasum = str(pin["shasum"])
    if not re.fullmatch(r"[0-9a-f]{40}", shasum):
        fail(f"{label} npm shasum is invalid")
    if hashlib.sha1(data).hexdigest() != shasum:
        fail(f"{label} npm shasum mismatch")
    return sha256_bytes(data)


def read_verified_npm_tarball(
    pin: dict[str, Any], *, label: str, max_bytes: int
) -> tuple[bytes, str]:
    source = str(pin["tarball"])
    allowed = {
        GROK_NPM_TARBALL,
        *(str(item["tarball"]) for item in NPM_NATIVE_PACKAGE_BY_HOST_ID.values()),
    }
    if source not in allowed:
        fail(f"{label} npm tarball source is not pinned")
    data = read_pinned_https_bytes(source, max_bytes=max_bytes, label=label)
    digest = verify_npm_dist_payload(data, pin, label)
    return data, digest


def safe_tgz_members(
    data: bytes,
    *,
    expected_files: set[str],
    expected_file_count: int,
    expected_unpacked_size: int,
    max_unpacked_size: int,
    label: str,
) -> dict[str, bytes]:
    try:
        archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
    except tarfile.TarError as exc:
        fail(f"{label} npm archive is invalid: {exc}")
    files: dict[str, bytes] = {}
    total = 0
    try:
        for member in archive.getmembers():
            name = member.name
            parts = PurePosixPath(name).parts
            if (
                not name
                or PurePosixPath(name).is_absolute()
                or any(part in {"", ".", ".."} for part in parts)
                or "\\" in name
            ):
                fail(f"{label} npm archive member path is unsafe: {name}")
            if not member.isfile():
                fail(f"{label} npm archive member is not a regular file: {name}")
            if name in files:
                fail(f"{label} npm archive contains duplicate member: {name}")
            if name not in expected_files:
                fail(f"{label} npm archive contains unexpected member: {name}")
            if member.mode & 0o022 or member.mode & 0o7000:
                fail(f"{label} npm archive member has unsafe mode: {name}")
            if member.uid != 0 or member.gid != 0:
                fail(f"{label} npm archive member owner is not root metadata: {name}")
            if member.size < 0:
                fail(f"{label} npm archive member size is invalid: {name}")
            total += int(member.size)
            if total > max_unpacked_size:
                fail(f"{label} npm archive exceeds unpacked size bound")
            extracted = archive.extractfile(member)
            if extracted is None:
                fail(f"{label} npm archive member cannot be read: {name}")
            payload = extracted.read(member.size + 1)
            if len(payload) != member.size:
                fail(f"{label} npm archive member changed while reading: {name}")
            files[name] = payload
    finally:
        archive.close()
    if set(files) != expected_files:
        fail(f"{label} npm archive member set mismatch")
    if len(files) != expected_file_count:
        fail(f"{label} npm archive file count mismatch")
    if total != expected_unpacked_size:
        fail(f"{label} npm archive unpacked size mismatch")
    return files


def load_package_json_member(files: dict[str, bytes], label: str) -> dict[str, Any]:
    try:
        value = json.loads(files["package/package.json"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"{label} package.json is invalid: {exc}")
    if not isinstance(value, dict):
        fail(f"{label} package.json must contain a JSON object")
    return value


def validate_umbrella_npm_package(files: dict[str, bytes]) -> dict[str, Any]:
    package = load_package_json_member(files, "umbrella Grok Build npm package")
    expected_optional = {
        pin["package"]: GROK_VERSION for pin in NPM_NATIVE_PACKAGE_BY_HOST_ID.values()
    }
    expected_optional.update(
        {package_name: GROK_VERSION for package_name in NPM_UNSUPPORTED_NATIVE_PACKAGE_OBSERVATIONS}
    )
    if package.get("name") != GROK_NPM_PACKAGE or package.get("version") != GROK_VERSION:
        fail("umbrella Grok Build npm package identity mismatch")
    if package.get("bin") != {GROK_COMMAND: "bin/grok"}:
        fail("umbrella Grok Build npm package bin mapping mismatch")
    if package.get("engines") != {"node": ">=20"}:
        fail("umbrella Grok Build npm package Node engine mismatch")
    if package.get("scripts") != {"postinstall": "node bin/postinstall.js"}:
        fail("umbrella Grok Build npm package script metadata mismatch")
    if package.get("optionalDependencies") != expected_optional:
        fail("umbrella Grok Build npm package optional dependency pins mismatch")
    wrapper = files["package/bin/grok"]
    if not wrapper.startswith(b"#!/usr/bin/env node\n"):
        fail("umbrella Grok Build npm package wrapper is invalid")
    return package


def validate_native_npm_package(files: dict[str, bytes], pin: dict[str, Any]) -> dict[str, Any]:
    package = load_package_json_member(files, "native Grok Build npm package")
    if package.get("name") != pin["package"] or package.get("version") != GROK_VERSION:
        fail("native Grok Build npm package identity mismatch")
    if package.get("os") != [pin["os"]] or package.get("cpu") != [pin["cpu"]]:
        fail("native Grok Build npm package platform mismatch")
    if "scripts" in package:
        fail("native Grok Build npm package must not define install scripts")
    binary_member = str(pin["binary_member"])
    if binary_member not in files or not files[binary_member]:
        fail("native Grok Build npm package binary payload is missing")
    return package


def selected_native_npm_pin(platform_info: RuntimePlatformInfo) -> dict[str, Any]:
    pin = NPM_NATIVE_PACKAGE_BY_HOST_ID.get(platform_info.host_id)
    if pin is None:
        fail(f"no pinned Grok Build npm package for host {platform_info.host_id}")
    return pin


def validate_node_runtime(path: Path) -> tuple[Path, str]:
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        fail(f"Node runtime is missing: {path}")
    try:
        before = resolved.lstat()
    except OSError as exc:
        fail(f"Node runtime cannot be inspected: {resolved}: {exc}")
    if not stat.S_ISREG(before.st_mode):
        fail(f"Node runtime must resolve to a regular file: {resolved}")
    if not os.access(resolved, os.X_OK):
        fail(f"Node runtime is not executable: {resolved}")
    try:
        completed = subprocess.run(
            [str(resolved), "--version"],
            env=minimal_process_env(),
            text=True,
            input="",
            capture_output=True,
            check=False,
            timeout=VERSION_PROBE_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        fail(f"Node runtime disappeared while validating: {exc}")
    except subprocess.TimeoutExpired:
        fail("Node runtime version probe timed out")
    if completed.returncode != 0:
        fail("Node runtime version probe failed")
    version = (completed.stdout + completed.stderr).strip()
    match = re.fullmatch(r"v(\d+)\.\d+\.\d+(?:[-+].*)?", version)
    if match is None or int(match.group(1)) < NODE_MINIMUM_MAJOR:
        fail("Grok Build npm materialization requires Node >=20")
    after = resolved.lstat()
    if (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        stat.S_IMODE(after.st_mode),
    ) != (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        stat.S_IMODE(before.st_mode),
    ):
        fail("Node runtime changed while validating")
    return resolved, version


def resolve_node_runtime() -> tuple[Path, str]:
    first_error: str | None = None
    for candidate in NODE_CANDIDATE_PATHS:
        try:
            return validate_node_runtime(candidate)
        except GrokBuildSetupError as exc:
            if first_error is None:
                first_error = str(exc)
    fail(first_error or "Grok Build npm materialization requires Node >=20")


def decompress_brotli_with_node(
    node_path: Path, node_version: str, compressed: bytes, stage: Path
) -> bytes:
    del node_version
    compressed_path = stage / "grok.br"
    output_path = stage / GROK_COMMAND
    compressed_path.write_bytes(compressed)
    compressed_path.chmod(OWNER_FILE_MODE)
    fsync_directory(stage, "Grok Build npm materialization stage")
    script = (
        "const fs=require('fs');"
        "const zlib=require('zlib');"
        "const [src,dst,maxRaw]=process.argv.slice(1);"
        "const raw=zlib.brotliDecompressSync(fs.readFileSync(src));"
        "if(raw.length>Number(maxRaw)){process.stderr.write('too large');process.exit(2);}"
        "fs.writeFileSync(dst,raw,{flag:'wx',mode:0o700});"
        "fs.chmodSync(dst,0o700);"
        "const fd=fs.openSync(dst,'r');"
        "try{fs.fsyncSync(fd);}finally{fs.closeSync(fd);}"
    )
    try:
        completed = subprocess.run(
            [
                str(node_path),
                "-e",
                script,
                str(compressed_path),
                str(output_path),
                str(SOFTWARE_MAX_BYTES),
            ],
            cwd=stage,
            env=minimal_process_env(tmp_dir=stage),
            text=True,
            input="",
            capture_output=True,
            check=False,
            timeout=VERSION_PROBE_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        fail(f"Node runtime disappeared while decompressing Grok Build binary: {exc}")
    except subprocess.TimeoutExpired:
        fail("Grok Build npm Brotli decompression timed out")
    if completed.returncode != 0:
        fail("Grok Build npm Brotli decompression failed: " + completed.stderr.strip())
    output_path.chmod(OWNER_EXEC_MODE)
    return read_software_file(output_path, f"Grok Build npm binary {output_path}")


def verify_staged_binary(binary: bytes, stage: Path) -> str:
    binary_path = stage / "probe-grok"
    binary_path.write_bytes(binary)
    binary_path.chmod(OWNER_EXEC_MODE)
    fsync_directory(stage, "Grok Build npm binary probe stage")
    probe_env = minimal_process_env(str(stage), tmp_dir=stage)
    probe_home = stage / "probe-home"
    probe_home.mkdir(mode=OWNER_DIRECTORY_MODE)
    probe_home.chmod(OWNER_DIRECTORY_MODE)
    probe_env["HOME"] = str(probe_home)
    probe_env["GROK_HOME"] = str(probe_home)
    try:
        probe = subprocess.run(
            [str(binary_path), "--version"],
            cwd=stage,
            env=probe_env,
            text=True,
            input="",
            capture_output=True,
            check=False,
            timeout=VERSION_PROBE_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        fail(f"Grok Build version probe executable is missing: {exc}")
    except subprocess.TimeoutExpired:
        fail("Grok Build version probe timed out")
    version_output = (probe.stdout + probe.stderr).strip()
    if probe.returncode != 0 or GROK_VERSION not in version_output:
        fail("Grok Build npm binary did not report the pinned version")
    return version_output


def materialize_verified_npm_artifact(target: Path) -> dict[str, Any]:
    platform_info = require_supported_runtime_platform()
    native_pin = selected_native_npm_pin(platform_info)
    node_path, node_version = resolve_node_runtime()
    umbrella_pin = {
        "package": GROK_NPM_PACKAGE,
        "integrity": GROK_NPM_INTEGRITY,
        "shasum": GROK_NPM_SHASUM,
        "tarball": GROK_NPM_TARBALL,
        "unpacked_size": GROK_NPM_UNPACKED_SIZE,
        "file_count": GROK_NPM_FILE_COUNT,
    }
    require_control_directory(managed_control_dir(target), "NDDev control root", allow_locked=False)
    ensure_private_directory(control_tmp_dir(target), "NDDev control tmp")
    with tempfile.TemporaryDirectory(prefix="npm.", dir=str(control_tmp_dir(target))) as stage_raw:
        stage = Path(stage_raw)
        stage.chmod(OWNER_DIRECTORY_MODE)
        umbrella_tgz, umbrella_sha256 = read_verified_npm_tarball(
            umbrella_pin,
            label="umbrella Grok Build npm tarball",
            max_bytes=GROK_NPM_TARBALL_MAX_BYTES,
        )
        native_tgz, native_sha256 = read_verified_npm_tarball(
            native_pin,
            label="native Grok Build npm tarball",
            max_bytes=NPM_NATIVE_TARBALL_MAX_BYTES,
        )
        umbrella_files = safe_tgz_members(
            umbrella_tgz,
            expected_files={
                "package/bin/grok",
                "package/bin/postinstall.js",
                "package/package.json",
                "package/README.md",
            },
            expected_file_count=GROK_NPM_FILE_COUNT,
            expected_unpacked_size=GROK_NPM_UNPACKED_SIZE,
            max_unpacked_size=GROK_NPM_UNPACKED_SIZE,
            label="umbrella Grok Build npm tarball",
        )
        native_files = safe_tgz_members(
            native_tgz,
            expected_files={
                str(native_pin["binary_member"]),
                "package/package.json",
                "package/README.md",
                "package/THIRD_PARTY_NOTICES.md",
            },
            expected_file_count=int(native_pin["file_count"]),
            expected_unpacked_size=int(native_pin["unpacked_size"]),
            max_unpacked_size=SOFTWARE_MAX_BYTES,
            label="native Grok Build npm tarball",
        )
        validate_umbrella_npm_package(umbrella_files)
        validate_native_npm_package(native_files, native_pin)
        binary = decompress_brotli_with_node(
            node_path,
            node_version,
            native_files[str(native_pin["binary_member"])],
            stage,
        )
        version_output = verify_staged_binary(binary, stage)
        return {
            "binary": binary,
            "binary_sha256": sha256_bytes(binary),
            "version_output": version_output,
            "install_mechanism": "verified-npm-tarball",
            "installer_source": INSTALLER_URL,
            "installer_sha256": INSTALLER_SHA256,
            "npm_package": GROK_NPM_PACKAGE,
            "npm_tarball": GROK_NPM_TARBALL,
            "npm_integrity": GROK_NPM_INTEGRITY,
            "npm_shasum": GROK_NPM_SHASUM,
            "npm_tarball_sha256": umbrella_sha256,
            "npm_tarball_size_bytes": len(umbrella_tgz),
            "npm_unpacked_size": GROK_NPM_UNPACKED_SIZE,
            "native_npm_package": native_pin["package"],
            "native_npm_tarball": native_pin["tarball"],
            "native_npm_integrity": native_pin["integrity"],
            "native_npm_shasum": native_pin["shasum"],
            "native_npm_tarball_sha256": native_sha256,
            "native_npm_tarball_size_bytes": len(native_tgz),
            "native_npm_unpacked_size": native_pin["unpacked_size"],
            "node_path": str(node_path),
            "node_version": node_version,
        }


def software_stamp(
    target: Path,
    *,
    artifact: dict[str, Any],
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
        "install_mechanism": "verified-npm-tarball",
        "installer_url": artifact["installer_source"],
        "installer_sha256": artifact["installer_sha256"],
        "installer_observation_only": True,
        "installer_exact_version_arg": GROK_VERSION,
        "npm_package": GROK_NPM_PACKAGE,
        "npm_version": GROK_VERSION,
        "npm_integrity": GROK_NPM_INTEGRITY,
        "npm_shasum": GROK_NPM_SHASUM,
        "npm_tarball": GROK_NPM_TARBALL,
        "npm_tarball_sha256": artifact["npm_tarball_sha256"],
        "npm_tarball_size_bytes": artifact["npm_tarball_size_bytes"],
        "npm_unpacked_size": artifact["npm_unpacked_size"],
        "native_npm_package": artifact["native_npm_package"],
        "native_npm_integrity": artifact["native_npm_integrity"],
        "native_npm_shasum": artifact["native_npm_shasum"],
        "native_npm_tarball": artifact["native_npm_tarball"],
        "native_npm_tarball_sha256": artifact["native_npm_tarball_sha256"],
        "native_npm_tarball_size_bytes": artifact["native_npm_tarball_size_bytes"],
        "native_npm_unpacked_size": artifact["native_npm_unpacked_size"],
        "node_path": artifact["node_path"],
        "node_version": artifact["node_version"],
        "package_scripts_disabled": True,
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
        "install_mechanism",
        "installer_url",
        "installer_sha256",
        "installer_observation_only",
        "installer_exact_version_arg",
        "npm_package",
        "npm_version",
        "npm_integrity",
        "npm_shasum",
        "npm_tarball",
        "npm_tarball_sha256",
        "npm_tarball_size_bytes",
        "npm_unpacked_size",
        "native_npm_package",
        "native_npm_integrity",
        "native_npm_shasum",
        "native_npm_tarball",
        "native_npm_tarball_sha256",
        "native_npm_tarball_size_bytes",
        "native_npm_unpacked_size",
        "node_path",
        "node_version",
        "package_scripts_disabled",
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
        platform_info = require_supported_runtime_platform()
        native_pin = selected_native_npm_pin(platform_info)
        if (
            value["channel"] != GROK_CHANNEL
            or value["install_mechanism"] != "verified-npm-tarball"
            or value["installer_observation_only"] is not True
            or value["installer_exact_version_arg"] != GROK_VERSION
            or value["npm_package"] != GROK_NPM_PACKAGE
            or value["npm_version"] != GROK_VERSION
            or value["npm_integrity"] != GROK_NPM_INTEGRITY
            or value["npm_shasum"] != GROK_NPM_SHASUM
            or value["npm_tarball"] != GROK_NPM_TARBALL
            or value["npm_unpacked_size"] != GROK_NPM_UNPACKED_SIZE
            or value["native_npm_package"] != native_pin["package"]
            or value["native_npm_integrity"] != native_pin["integrity"]
            or value["native_npm_shasum"] != native_pin["shasum"]
            or value["native_npm_tarball"] != native_pin["tarball"]
            or value["native_npm_unpacked_size"] != native_pin["unpacked_size"]
            or value["package_scripts_disabled"] is not True
        ):
            fail("Grok Build software stamp provenance is invalid")
        for digest_key in ("npm_tarball_sha256", "native_npm_tarball_sha256"):
            if not isinstance(value[digest_key], str) or not re.fullmatch(
                r"[0-9a-f]{64}", value[digest_key]
            ):
                fail(f"Grok Build software stamp {digest_key} must be a SHA-256 digest")
        for size_key in ("npm_tarball_size_bytes", "native_npm_tarball_size_bytes"):
            if not isinstance(value[size_key], int) or value[size_key] <= 0:
                fail(f"Grok Build software stamp {size_key} is invalid")
        if (
            value["npm_tarball_size_bytes"] > GROK_NPM_TARBALL_MAX_BYTES
            or value["native_npm_tarball_size_bytes"] > NPM_NATIVE_TARBALL_MAX_BYTES
        ):
            fail("Grok Build software stamp tarball size exceeds bounds")
        if not isinstance(value["node_path"], str) or not value["node_path"].startswith("/"):
            fail("Grok Build software stamp node_path is invalid")
        if not isinstance(value["node_version"], str) or not re.fullmatch(
            r"v\d+\.\d+\.\d+(?:[-+].*)?", value["node_version"]
        ):
            fail("Grok Build software stamp node_version is invalid")
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
    require_supported_runtime_platform()
    return read_lifecycle_payload(target, software_status_locked)


def software_status_locked(target: Path, *, validate_cleanup: bool = True) -> dict[str, Any]:
    canonical = validate_target(target, create=False)
    pending_cleanup = (
        cleanup_pending_metadata(canonical)
        if validate_cleanup
        else {
            "cleanup_pending": False,
            "cleanup_pending_roots": 0,
            "cleanup_pending_entries": 0,
        }
    )
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
        **pending_cleanup,
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
            "install_mechanism": "verified-npm-tarball",
            "installer_url": INSTALLER_URL,
            "installer_sha256": INSTALLER_SHA256,
            "installer_observation_only": True,
            "installer_exact_version_arg": GROK_VERSION,
            "npm_package": GROK_NPM_PACKAGE,
            "npm_version": GROK_VERSION,
            "npm_integrity": GROK_NPM_INTEGRITY,
            "npm_shasum": GROK_NPM_SHASUM,
            "npm_tarball": GROK_NPM_TARBALL,
            "npm_unpacked_size": GROK_NPM_UNPACKED_SIZE,
            "package_scripts_disabled": True,
        }
        native_pin = selected_native_npm_pin(require_supported_runtime_platform())
        expected.update(
            {
                "native_npm_package": native_pin["package"],
                "native_npm_integrity": native_pin["integrity"],
                "native_npm_shasum": native_pin["shasum"],
                "native_npm_tarball": native_pin["tarball"],
                "native_npm_unpacked_size": native_pin["unpacked_size"],
            }
        )
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


def install_grok_software(target: Path, command: str) -> dict[str, Any]:
    require_supported_runtime_platform()
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
                    "cleanup_pending": False,
                    "managed_command": str(managed_grok_path(target).resolve(strict=False)),
                }
            validate_safe_software_presence(target)
            snapshot = snapshot_software_state(
                target,
                preserve_paths=(
                    software_tree_binary(target),
                    managed_grok_path(target),
                    software_stamp_path(target),
                ),
            )
            cleanup_pending_result = False
            try:
                artifact = materialize_verified_npm_artifact(target)
                stamp_bytes = canonical_json(
                    software_stamp(
                        target,
                        artifact=artifact,
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
                validate_intended_software_state(target, stamp_bytes, artifact["binary"])
                cleanup_pending_result = finish_journaled_cleanup(
                    target,
                    collect_cleanup_roots(
                        target,
                        preserved_files=snapshot.preserved_files,
                        preserved_trees=snapshot.preserved_trees,
                    ),
                    lambda: (
                        cleanup_preserved_stage_roots_retry(snapshot.preserved_files),
                        cleanup_preserved_tree_stage_roots_retry(snapshot.preserved_trees),
                        restore_tree_retry(
                            control_tmp_dir(target),
                            snapshot.control_tmp,
                            max_bytes=SOFTWARE_MAX_BYTES,
                            label="control tmp",
                        ),
                    ),
                )
            except PostCommitCleanupError:
                raise
            except BaseException:
                restore_software_snapshot_retry(target, snapshot)
                raise
            final_status = software_status_locked(
                target, validate_cleanup=not cleanup_pending_result
            )
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
                "cleanup_pending": cleanup_pending_result,
                "managed_command": str(managed_grok_path(target).resolve(strict=False)),
            }
        except BaseException:
            raise


def remove_grok_software(target: Path) -> dict[str, Any]:
    require_supported_runtime_platform()
    with target_lock(target, create=False, allow_missing=True) as target:
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
                "cleanup_pending": False,
                "managed_command": str(managed_grok_path(target).resolve(strict=False)),
            }
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
                "cleanup_pending": False,
                "managed_command": str(managed_grok_path(target).resolve(strict=False)),
            }
        validate_safe_software_presence(target)
        preserve_paths: list[Path] = []
        preserve_trees: list[Path] = []
        if managed_grok_path(target).exists() and not managed_grok_path(target).is_symlink():
            bin_entries = (
                sorted(managed_grok_path(target).parent.iterdir(), key=lambda item: item.name)
                if managed_grok_path(target).parent.exists()
                and not managed_grok_path(target).parent.is_symlink()
                else []
            )
            if [entry.name for entry in bin_entries] == [GROK_COMMAND]:
                preserve_trees.append(managed_grok_path(target).parent)
            else:
                preserve_paths.append(managed_grok_path(target))
        if software_root(target).exists() and not software_root(target).is_symlink():
            container_entries = (
                sorted(software_container(target).iterdir(), key=lambda item: item.name)
                if software_container(target).exists()
                and not software_container(target).is_symlink()
                else []
            )
            if [entry.name for entry in container_entries] == ["grok-build"]:
                preserve_trees.append(software_container(target))
            else:
                preserve_trees.append(software_root(target))
        snapshot = snapshot_software_state(
            target,
            preserve_paths=preserve_paths,
            preserve_trees=preserve_trees,
        )
        removed = software_present_paths_from_snapshot(snapshot)
        cleanup_pending_result = False
        try:
            remove_grok_software_state_once(target)
            validate_removed_software_state(target)
            cleanup_pending_result = finish_journaled_cleanup(
                target,
                collect_cleanup_roots(
                    target,
                    preserved_files=snapshot.preserved_files,
                    preserved_trees=snapshot.preserved_trees,
                ),
                lambda: (
                    cleanup_preserved_stage_roots_retry(snapshot.preserved_files),
                    cleanup_preserved_tree_stage_roots_retry(snapshot.preserved_trees),
                    restore_tree_retry(
                        control_tmp_dir(target),
                        snapshot.control_tmp,
                        max_bytes=SOFTWARE_MAX_BYTES,
                        label="control tmp",
                    ),
                ),
            )
        except PostCommitCleanupError:
            raise
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
            "cleanup_pending": cleanup_pending_result,
            "managed_command": str(managed_grok_path(target).resolve(strict=False)),
        }


def plan_payload(target: Path, setup: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    require_supported_runtime_platform()

    def build_plan(target: Path) -> dict[str, Any]:
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
            "cleanup_pending": status.get("cleanup_pending", False),
            "cleanup_pending_roots": status.get("cleanup_pending_roots", 0),
            "cleanup_pending_entries": status.get("cleanup_pending_entries", 0),
        }

    return read_lifecycle_payload(target, build_plan)


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
                require_lockable_directory(
                    image_parent, "Grok Build launch image directory", allow_locked=True
                )
                image_parent.chmod(OWNER_DIRECTORY_MODE)
                require_lockable_directory(
                    image_parent, "Grok Build launch image directory", allow_locked=False
                )
            with contextlib.suppress(FileNotFoundError):
                launch_image.unlink()
            with contextlib.suppress(FileNotFoundError, OSError):
                image_parent.rmdir()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = JsonArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(
        dest="command", required=True, parser_class=JsonArgumentParser
    )
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
    update = subparsers.add_parser("update")
    update.add_argument("--target", required=True)
    update.add_argument("--json", action="store_true")
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
    require_command_supported_host(args.command)
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
    if args.command == "update":
        target = require_absolute_target(args.target)
        emit(update_setup(target), as_json=args.json)
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
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parse_args(raw_argv)
        return dispatch(args)
    except JsonArgumentParseError as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True))
        return 2
    except GrokBuildSetupError as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
