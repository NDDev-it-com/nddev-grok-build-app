#!/usr/bin/env python3
"""Transactional setup manager for an explicit Grok Build home."""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="ascii").strip()
PRODUCT_NAME = "nddev-grok-build-app"
SETUP_ROOT = ROOT / "setups"
BUILDER_ROOT = ROOT / "builder" / "nddev-builder"
SETUP_ORDER = ("safe", "balanced", "full-auto")
STAMP_NAME = "NDDEV-GROK-BUILD-SETUP.json"
BACKUP_NAME = "NDDEV-GROK-BUILD-BACKUP.json"
SOFTWARE_STAMP_NAME = "NDDEV-GROK-BUILD-SOFTWARE.json"
MANAGED_BEGIN = "# BEGIN NDDEV-GROK-BUILD MANAGED"
MANAGED_END = "# END NDDEV-GROK-BUILD MANAGED"
OWNER_FILE_MODE = 0o600
OWNER_DIRECTORY_MODE = 0o700
OWNER_EXEC_MODE = 0o700
MANAGED_MAX_BYTES = 8 * 1024 * 1024
METADATA_MAX_BYTES = 256 * 1024
SOFTWARE_MAX_BYTES = 256 * 1024 * 1024
GROK_COMMAND = "grok"
GROK_VERSION = "0.2.112"
INSTALLER_URL = "https://x.ai/cli/install.sh"
INSTALLER_SHA256 = "0465d810453bbf18608ccae310fa79f4c59ae4a0538bd8a3a374ebce749be952"
INTERNAL_INSTALLER_URL_ENV = "NDDEV_GROK_BUILD_TEST_INSTALLER_URL"
INTERNAL_FAIL_AFTER_VERSION_SWAP_ENV = "NDDEV_GROK_BUILD_TEST_FAIL_AFTER_VERSION_SWAP"
INTERNAL_FAIL_AFTER_BINARY_SWAP_ENV = "NDDEV_GROK_BUILD_TEST_FAIL_AFTER_BINARY_SWAP"
INTERNAL_INSTALLER_TIMEOUT_ENV = "NDDEV_GROK_BUILD_TEST_INSTALLER_TIMEOUT_SECONDS"
INTERNAL_PROBE_TIMEOUT_ENV = "NDDEV_GROK_BUILD_TEST_PROBE_TIMEOUT_SECONDS"
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
    "--yolo",
    "-c",
}
CONTENT_MANAGED_PATHS = (
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


class GrokBuildSetupError(Exception):
    """Safe user-facing lifecycle failure."""


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


def validate_target(target: Path, *, create: bool = False) -> Path:
    parent = target.parent
    if create:
        create_missing_directories(missing_directory_chain(parent))
        require_real_directory(parent, "target parent")
    else:
        parent_info = stat_existing(parent, "target parent")
        if parent_info is None:
            return target.resolve(strict=False)
        if not stat.S_ISDIR(parent_info.st_mode):
            fail("target parent must be a directory")
    info = stat_existing(target, "target")
    if info is None:
        if not create:
            return target.resolve(strict=False)
        target.mkdir(mode=OWNER_DIRECTORY_MODE)
        target.chmod(OWNER_DIRECTORY_MODE)
        return target.resolve()
    if not stat.S_ISDIR(info.st_mode):
        fail("target must be a real directory")
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


def backup_pool(target: Path) -> Path:
    return target.parent / f".{target.name}.nddev-grok-build-backups"


def lock_path(target: Path) -> Path:
    return target.parent / f".{target.name}.nddev-grok-build.lock"


@contextlib.contextmanager
def target_lock(target: Path):
    created_parent_chain = missing_directory_chain(target.parent)
    create_missing_directories(created_parent_chain)
    require_real_directory(target.parent, "target parent")
    path = lock_path(target)
    try:
        path.mkdir(mode=OWNER_DIRECTORY_MODE)
    except FileExistsError:
        fail(f"target is locked: {path}")
    try:
        yield
    finally:
        with contextlib.suppress(FileNotFoundError):
            path.rmdir()
        remove_created_empty_directories(created_parent_chain)


def safe_target_path(target: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        fail(f"invalid managed path: {relative}")
    return target / candidate


def ensure_real_parent(path: Path, target: Path) -> None:
    relative_parent = path.relative_to(target).parent
    current = target
    for part in relative_parent.parts:
        current = current / part
        info = stat_existing(current, f"managed directory {current}")
        if info is None:
            current.mkdir(mode=OWNER_DIRECTORY_MODE)
            continue
        if not stat.S_ISDIR(info.st_mode):
            fail(f"managed parent is not a directory: {current}")


def require_existing_managed_file(
    path: Path, label: str, *, max_bytes: int
) -> os.stat_result | None:
    info = stat_existing(path, label)
    if info is None:
        return None
    if not stat.S_ISREG(info.st_mode):
        fail(f"{label} must be a regular file")
    if info.st_nlink != 1:
        fail(f"{label} must not be a hardlink")
    if info.st_size > max_bytes:
        fail(f"{label} is too large")
    return info


def read_existing_file(path: Path, *, max_bytes: int, label: str) -> bytes | None:
    info = require_existing_managed_file(path, label, max_bytes=max_bytes)
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


def read_json_file(path: Path, *, max_bytes: int, label: str) -> dict[str, Any]:
    data = read_existing_file(path, max_bytes=max_bytes, label=label)
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


def list_setups() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for setup_id in SETUP_ORDER:
        setup = load_setup(setup_id)
        items.append(
            {
                "id": setup["id"],
                "display_name": setup["display_name"],
                "description": setup["description"],
                "permission_mode": setup["permission_mode"],
                "sandbox_profile": setup["sandbox_profile"],
                "nddev_builder_default": setup["nddev_builder_default"],
            }
        )
    return items


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


def render_config(setup: dict[str, Any]) -> str:
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
        "\n"
        "[ui]\n"
        f"permission_mode = {toml_string(setup['permission_mode'])}\n"
        "remember_tool_approvals = false\n"
        'default_selected_permission = "allow_once"\n'
        'screen_mode = "fullscreen"\n'
        "\n"
        "[sandbox]\n"
        f"profile = {toml_string(setup['sandbox_profile'])}\n"
        "auto_allow_bash = false\n"
        "\n"
        "[features]\n"
        f"web_fetch = {toml_bool(bool(setup['web_fetch']))}\n"
        f"write_file = {toml_bool(bool(setup['write_file']))}\n"
        f"tool_search = {toml_bool(bool(setup['tool_search']))}\n"
        f"lsp_tools = {toml_bool(bool(setup['lsp_tools']))}\n"
        "\n"
        "[subagents]\n"
        f"enabled = {toml_bool(bool(setup['subagents_enabled']))}\n"
        "\n"
        "[subagents.toggle]\n"
        "explore = true\n"
        "plan = true\n"
        "\n"
        "[plugins]\n"
        'enabled = ["nddev-builder"]\n'
        "\n"
        "[permission]\n"
        f"deny = {toml_array(list(setup['permission_deny']))}\n"
        f"ask = {toml_array(list(setup['permission_ask']))}\n"
        f"{MANAGED_END}\n"
    )


def render_agents_block(setup: dict[str, Any]) -> str:
    return (
        f"{MANAGED_BEGIN}\n"
        "# Managed by nddev-grok-build-app. Edit outside this block to preserve local rules.\n"
        "\n"
        "# NDDev Grok Build Setup\n"
        "\n"
        f"This Grok Build home is managed as the `{setup['id']}` setup by nddev-grok-build-app.\n"
        "Use only current Grok Build surfaces documented by xAI: `AGENTS.md`, `.grok/rules/`,\n"
        "`$GROK_HOME/skills/`, `$GROK_HOME/agents/`, hooks, MCP configuration, and plugins.\n"
        "Do not use stale Grok Build command identities or unsupported marketplace assumptions.\n"
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


def desired_files(target: Path, setup: dict[str, Any]) -> dict[str, bytes]:
    existing_config = read_existing_file(
        target / "config.toml", max_bytes=MANAGED_MAX_BYTES, label="config.toml"
    )
    existing_agents = read_existing_file(
        target / "AGENTS.md", max_bytes=MANAGED_MAX_BYTES, label="AGENTS.md"
    )
    skill = builder_source("skills/nddev-builder/SKILL.md")
    agent = builder_source("agents/nddev-builder.md")
    return {
        "config.toml": merge_managed_block(existing_config, render_config(setup)),
        "AGENTS.md": merge_managed_block(existing_agents, render_agents_block(setup)),
        "skills/nddev-builder/SKILL.md": skill,
        "agents/nddev-builder.md": agent,
        "plugins/nddev-builder/plugin.json": builder_source("plugin.json"),
        "plugins/nddev-builder/skills/nddev-builder/SKILL.md": skill,
        "plugins/nddev-builder/agents/nddev-builder.md": agent,
    }


def managed_digest_for_bytes(relative: str, data: bytes) -> str:
    if relative in MERGED_MARKER_PATHS:
        block = extract_managed_block(data.decode("utf-8"))
        if block is None:
            return ""
        return sha256_bytes(block.encode("utf-8"))
    return sha256_bytes(data)


def current_managed_digest(target: Path, relative: str) -> str | None:
    data = read_existing_file(
        safe_target_path(target, relative), max_bytes=MANAGED_MAX_BYTES, label=relative
    )
    if data is None:
        return None
    digest = managed_digest_for_bytes(relative, data)
    return digest or None


def stamp_path(target: Path) -> Path:
    return target / STAMP_NAME


def read_stamp(target: Path) -> dict[str, Any] | None:
    path = stamp_path(target)
    if not path.exists():
        return None
    stamp = read_json_file(path, max_bytes=METADATA_MAX_BYTES, label=STAMP_NAME)
    if stamp.get("product_name") != PRODUCT_NAME:
        fail("stamp belongs to another product")
    canonical = str(validate_target(target, create=False))
    if stamp.get("canonical_target") != canonical:
        fail("stamp is bound to a different canonical target")
    return stamp


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
    canonical = validate_target(target, create=False)
    if not target.exists():
        return {
            "state": "absent",
            "managed": False,
            "canonical_target": str(canonical),
            "setup_id": None,
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
            "drift": [],
        }
    return {
        "state": "managed",
        "managed": True,
        "canonical_target": str(canonical),
        "setup_id": stamp["setup_id"],
        "build_version": stamp["build_version"],
        "drift": drift_for_stamp(target, stamp),
        "managed_files": sorted(stamp["managed_files"]),
    }


def snapshot_files(target: Path) -> dict[str, bytes | None]:
    snapshot: dict[str, bytes | None] = {}
    for relative in (*CONTENT_MANAGED_PATHS, STAMP_NAME):
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
    create_missing_directories(missing_directory_chain(pool.parent))
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
        shutil.rmtree(slot_dir)
    slot_dir.mkdir(mode=OWNER_DIRECTORY_MODE)
    files: dict[str, Any] = {}
    for relative in (*CONTENT_MANAGED_PATHS, STAMP_NAME):
        data = read_existing_file(
            safe_target_path(target, relative), max_bytes=MANAGED_MAX_BYTES, label=relative
        )
        files[relative] = None if data is None else base64.b64encode(data).decode("ascii")
    envelope = {
        "schema_version": 1,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "slot": slot,
        "canonical_target": str(validate_target(target, create=False)),
        "source_setup_id": stamp["setup_id"],
        "created_at": int(time.time()),
        "files": files,
    }
    atomic_write(slot_dir / BACKUP_NAME, canonical_json(envelope), slot_dir)
    return slot


def build_stamp(target: Path, setup_id: str, files: dict[str, bytes]) -> dict[str, Any]:
    managed = {
        relative: managed_digest_for_bytes(relative, data) for relative, data in files.items()
    }
    return {
        "schema_version": 1,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "setup_id": setup_id,
        "canonical_target": str(validate_target(target, create=False)),
        "managed_files": managed,
    }


def write_setup(
    target: Path, setup: dict[str, Any], *, require_existing: bool = False
) -> dict[str, Any]:
    with target_lock(target):
        validate_target(target, create=True)
        current = read_stamp(target)
        if require_existing and current is None:
            fail("switch requires an already managed target")
        if current is not None:
            drift = drift_for_stamp(target, current)
            if drift:
                fail(f"managed target has drift: {', '.join(drift)}")
        files = desired_files(target, setup)
        desired_stamp = build_stamp(target, setup["id"], files)
        changed = [
            relative
            for relative, data in files.items()
            if current_managed_digest(target, relative) != managed_digest_for_bytes(relative, data)
        ]
        backup_slot = None
        if current is not None and current["setup_id"] != setup["id"]:
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
            "changed": changed,
            "backup_slot": backup_slot,
            "target": str(validate_target(target, create=False)),
        }


def restore_backup(target: Path, slot: int) -> dict[str, Any]:
    if slot < 0 or slot > 9:
        fail("backup slot must be between 0 and 9")
    with target_lock(target):
        validate_target(target, create=True)
        envelope_path = backup_pool(target) / str(slot) / BACKUP_NAME
        envelope = read_json_file(envelope_path, max_bytes=METADATA_MAX_BYTES, label=BACKUP_NAME)
        if envelope.get("product_name") != PRODUCT_NAME:
            fail("backup belongs to another product")
        if envelope.get("canonical_target") != str(validate_target(target, create=False)):
            fail("backup is bound to a different canonical target")
        files = envelope.get("files")
        if not isinstance(files, dict):
            fail("backup files are invalid")
        snapshot = snapshot_files(target)
        try:
            for relative in (*CONTENT_MANAGED_PATHS, STAMP_NAME):
                encoded = files.get(relative)
                path = safe_target_path(target, relative)
                if encoded is None:
                    with contextlib.suppress(FileNotFoundError):
                        path.unlink()
                    continue
                if not isinstance(encoded, str):
                    fail("backup file payload is invalid")
                atomic_write(path, base64.b64decode(encoded.encode("ascii")), target)
            prune_empty_managed_dirs(target)
        except BaseException:
            restore_snapshot(target, snapshot)
            raise
        restored_stamp = read_stamp(target)
        return {
            "setup_id": None if restored_stamp is None else restored_stamp["setup_id"],
            "backup_slot": slot,
            "target": str(validate_target(target, create=False)),
        }


def remove_setup(target: Path) -> dict[str, Any]:
    with target_lock(target):
        validate_target(target, create=False)
        stamp = read_stamp(target)
        if stamp is None:
            return {"removed_setup_id": None, "target": str(validate_target(target, create=False))}
        drift = drift_for_stamp(target, stamp)
        if drift:
            fail(f"managed target has drift: {', '.join(drift)}")
        removed_setup_id = stamp["setup_id"]
        snapshot = snapshot_files(target)
        try:
            for relative in CONTENT_MANAGED_PATHS:
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
    for relative in CONTENT_MANAGED_PATHS:
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


def read_url_or_file(source: str, *, max_bytes: int) -> bytes:
    if source.startswith("file://"):
        return read_software_file(
            Path(source[7:]), f"Grok Build installer {source}", max_bytes=max_bytes
        )
    request = urllib.request.Request(source, headers={"User-Agent": f"{PRODUCT_NAME}/{VERSION}"})
    with urllib.request.urlopen(request, timeout=60) as response:
        expected_length = response.headers.get("Content-Length")
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
    content = b"".join(chunks)
    if expected_length is not None and int(expected_length) != len(content):
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


def installer_source_url() -> str:
    return os.environ.get(INTERNAL_INSTALLER_URL_ENV) or INSTALLER_URL


def internal_timeout_seconds(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        timeout = float(value)
    except ValueError:
        fail(f"{name} must be a positive timeout in seconds")
    if timeout <= 0:
        fail(f"{name} must be a positive timeout in seconds")
    return timeout


def read_pinned_installer() -> tuple[bytes, str, str]:
    source = installer_source_url()
    installer = read_url_or_file(source, max_bytes=2 * 1024 * 1024)
    digest = sha256_bytes(installer)
    if source == INSTALLER_URL and digest != INSTALLER_SHA256:
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
        "schema_version": 1,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "canonical_target": str(validate_target(target, create=False)),
        "command": GROK_COMMAND,
        "version": GROK_VERSION,
        "installer_url": installer_source,
        "installer_sha256": installer_sha256,
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
        "installer_url",
        "installer_sha256",
        "binary_sha256",
        "version_output",
        "installed_at",
    }
    try:
        if set(value) != required:
            fail("Grok Build software stamp has invalid keys")
        if (
            value["schema_version"] != 1
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
            "installer_url": INSTALLER_URL,
            "installer_sha256": INSTALLER_SHA256,
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
    with tempfile.TemporaryDirectory(
        prefix=f".{target.name}.nddev-grok-build-installer.", dir=str(target.parent)
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
                "GROK_CHANNEL": "stable",
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
                timeout=internal_timeout_seconds(INTERNAL_INSTALLER_TIMEOUT_ENV, 120.0),
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
                timeout=internal_timeout_seconds(INTERNAL_PROBE_TIMEOUT_ENV, 15.0),
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
    with target_lock(target):
        before_target_exists = target.exists() or target.is_symlink()
        validate_target(target, create=True)
        try:
            require_private_directory(target, "target")
            status = software_status(target)
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
                if os.environ.get(INTERNAL_FAIL_AFTER_VERSION_SWAP_ENV) == "1":
                    fail("injected failure after Grok Build version swap")
                software_atomic_write(
                    managed_grok_path(target), artifact["binary"], target, OWNER_EXEC_MODE
                )
                if os.environ.get(INTERNAL_FAIL_AFTER_BINARY_SWAP_ENV) == "1":
                    fail("injected failure after Grok Build binary swap")
                software_atomic_write(
                    software_stamp_path(target), stamp_bytes, target, OWNER_FILE_MODE
                )
                final_status = software_status(target)
                if not final_status["installed"]:
                    fail(
                        "Grok Build software install did not produce structurally complete target-owned software"
                    )
                if installer_source == INSTALLER_URL:
                    if not final_status["current"]:
                        fail("Grok Build software install did not produce current pinned software")
                else:
                    structural = [
                        item
                        for item in final_status["drift"]
                        if item not in {"installer_url", "installer_sha256"}
                    ]
                    if structural:
                        fail(
                            "Grok Build test installer produced structural drift: "
                            + ", ".join(structural)
                        )
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
            final_status = software_status(target)
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


def plan_payload(target: Path, setup: dict[str, Any]) -> dict[str, Any]:
    status = status_payload(target)
    operation = "install"
    backup_required = False
    if status["managed"]:
        operation = "update" if status["setup_id"] == setup["id"] else "switch"
        backup_required = status["setup_id"] != setup["id"]
    return {
        "operation": operation,
        "setup_id": setup["id"],
        "target": str(validate_target(target, create=False)),
        "current_setup_id": status["setup_id"],
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


def launch(target: Path, child_args: list[str]) -> int:
    override = child_args_use_target_scope_overrides(child_args)
    if override is not None:
        fail(f"launch child arguments must not override target-owned Grok Build scope: {override}")
    with target_lock(target):
        status = status_payload(target)
        if not status["managed"]:
            fail("launch requires a managed target")
        if status["drift"]:
            fail(f"managed target has drift: {', '.join(status['drift'])}")
        software = software_status(target)
        if not software["installed"] or not software["current"]:
            fail("launch requires current target-owned Grok Build software")
        setup = load_setup(str(status["setup_id"]))
        canonical = validate_target(target, create=False)
        runtime_root = canonical / ".nddev-grok-build-runtime"
        home = runtime_root / "home"
        tmp = runtime_root / "tmp"
        create_missing_directories(missing_directory_chain(home))
        create_missing_directories(missing_directory_chain(tmp))
        require_private_directory(runtime_root, "Grok Build runtime root")
        require_private_directory(home, "Grok Build runtime HOME")
        require_private_directory(tmp, "Grok Build runtime TMPDIR")
        executable = managed_grok_path(target)
        child_env: dict[str, str] = {
            "HOME": str(home),
            "GROK_HOME": str(canonical),
            "GROK_DISABLE_AUTOUPDATER": "1",
            "GROK_SANDBOX": str(setup["sandbox_profile"]),
            "GROK_SUBAGENTS": "1" if setup["subagents_enabled"] else "0",
            "GROK_WEB_FETCH": "1" if setup["web_fetch"] else "0",
            "GROK_MEMORY": "0",
            "PATH": SAFE_SYSTEM_PATH,
            "TMPDIR": str(tmp),
        }
        for name in ("TERM", "COLORTERM", "LANG", "LC_ALL", "LC_CTYPE", "SYSTEMROOT"):
            value = os.environ.get(name)
            if value:
                child_env[name] = value
        for name in PROVIDER_SECRET_NAMES:
            child_env.pop(name, None)
    completed = subprocess.run([str(executable), *child_args], env=child_env, check=False)
    return int(completed.returncode)


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
        command.add_argument("--setup", required=True)
        command.add_argument("--target", required=True)
        command.add_argument("--json", action="store_true")
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
        emit({"setups": [item["id"] for item in items], "items": items}, as_json=args.json)
        return 0
    if args.command == "status":
        emit(status_payload(require_absolute_target(args.target)), as_json=args.json)
        return 0
    if args.command == "software-status":
        emit(software_status(require_absolute_target(args.target)), as_json=args.json)
        return 0
    if args.command == "plan":
        target = require_absolute_target(args.target)
        emit(plan_payload(target, load_setup(args.setup)), as_json=args.json)
        return 0
    if args.command == "install":
        target = require_absolute_target(args.target)
        emit(write_setup(target, load_setup(args.setup)), as_json=args.json)
        return 0
    if args.command == "switch":
        target = require_absolute_target(args.target)
        emit(write_setup(target, load_setup(args.setup), require_existing=True), as_json=args.json)
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
