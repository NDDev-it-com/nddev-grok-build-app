#!/usr/bin/env python3
"""Validate public nddev-grok-build-app release contracts."""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
SHARED_CI_COMMIT = "2ccb80e96f5771b6a6b4eae63a4f47e232906dc7"
SHARED_CI_VERSION = "0.12.0"
REQUIRED_WORKFLOWS = {
    "actionlint.yml": ".github/workflows/actionlint.yml",
    "codeql.yml": ".github/workflows/public-codeql.yml",
    "dependency-review.yml": ".github/workflows/public-dependency-review.yml",
    "release.yml": ".github/workflows/release-supply-chain.yml",
    "scorecard.yml": ".github/workflows/public-scorecard-json.yml",
    "secret-scan.yml": ".github/workflows/secret-scan.yml",
    "zizmor.yml": ".github/workflows/zizmor-sarif.yml",
}
RELEASE_PERMISSIONS = {
    "contents": "write",
    "id-token": "write",
    "attestations": "write",
    "artifact-metadata": "write",
}
RELEASE_GOVERNANCE_PATHS = {
    "README.md",
    "LICENSE",
    "VERSION",
    "CHANGELOG.md",
    "AGENTS.md",
    ".claude",
    ".gds",
    ".github",
}
CLAUDE_BRIDGE_ROOT = ".claude"
CLAUDE_BRIDGE_PATH = ".claude/CLAUDE.md"
CLAUDE_BRIDGE_TARGET = "AGENTS.md"
CLAUDE_BRIDGE_BYTES = b"@../AGENTS.md\n"
RELEASE_ARCHIVE_REQUIRED_PATHS = {
    *RELEASE_GOVERNANCE_PATHS,
    "build",
    "builder",
    "cli-tools",
    "config",
    "docs",
    "profiles",
    "references",
    "setups",
}
SETUP_ORDER = ["nddev-builder"]
PROFILE_ORDER = ["full-auto", "safe"]
GROK_VERSION = "0.2.112"
NPM_PACKAGE = "@xai-official/grok"
NPM_INTEGRITY = (
    "sha512-dCXAiFHmn3JTOK+vPfCIzzum1GmxPB81NH73yYhqleXx1y/Ks3qjwJ+GeEXmB7eudiap98j9Nj1cDwH4lSuaOw=="
)
NPM_SHASUM = "cd103bfeb3d102dff87788a9cbe8d36c293112c8"
INSTALLER_URL = "https://x.ai/cli/install.sh"
INSTALLER_SHA256 = "0465d810453bbf18608ccae310fa79f4c59ae4a0538bd8a3a374ebce749be952"
METADATA_MAX_BYTES = 256 * 1024
SOFTWARE_LIFECYCLE_KEYS = {
    "channel",
    "command",
    "credential_inheritance",
    "discarded_stage_paths",
    "entrypoint",
    "fetch_errors_are_domain_errors",
    "install_command",
    "install_precondition",
    "installer_exact_version_arg",
    "installer_sha256",
    "npm_integrity",
    "npm_package",
    "npm_shasum",
    "npm_tarball",
    "official_installer",
    "persisted_stage_paths",
    "presence_signal",
    "private_modes",
    "rollback_on_failure",
    "software_root",
    "stage_env",
    "stamp_file",
    "stamp_schema",
    "status_command",
    "status_executes_binary",
    "target_owned",
    "update_command",
    "update_precondition",
    "version",
    "version_probe",
}
BUILDER_SKILLS = {
    "nddev-builder",
    "grok-config-profile",
    "grok-permissions-sandbox",
    "grok-agents-subagents",
    "grok-skills-instructions",
    "grok-plugins-marketplace",
    "grok-hooks",
    "grok-mcp",
    "grok-install-lifecycle",
    "grok-creator-checker-release",
}
FORBIDDEN_MANAGER_SOURCE_MARKERS = {
    "NDDEV_GROK_BUILD_TEST",
    "NDDEV_GROK_BUILD_BOOTSTRAP",
    "NDDEV_GROK_BUILD_LOCK",
    "ALLOW_TEST",
    "FAIL_AFTER",
    "TEST_INSTALLER",
    "TEST_PROBE",
    "TEST_TIMEOUT",
    "BOOTSTRAP_ROOT_OVERRIDE",
    "LOCK_ROOT_OVERRIDE",
    "installer_source_url",
    "internal_timeout_seconds",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    return parser.parse_args(argv)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def leading_spaces(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def parse_workflow_mapping(lines: list[str], header: str, indent: int) -> dict[str, str]:
    start = None
    for index, line in enumerate(lines):
        if leading_spaces(line) == indent and line.strip() == f"{header}:":
            start = index + 1
            break
    if start is None:
        raise ValueError(f"release workflow missing {header} mapping")
    values: dict[str, str] = {}
    index = start
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        current_indent = leading_spaces(line)
        if not stripped:
            index += 1
            continue
        if current_indent <= indent:
            break
        if current_indent == indent + 2 and ":" in stripped:
            key, raw = stripped.split(":", 1)
            raw = raw.strip()
            if raw == ">-":
                chunks: list[str] = []
                index += 1
                while index < len(lines):
                    folded = lines[index]
                    folded_stripped = folded.strip()
                    if not folded_stripped:
                        index += 1
                        continue
                    if leading_spaces(folded) <= current_indent:
                        break
                    chunks.append(folded_stripped)
                    index += 1
                values[key] = " ".join(chunks)
                continue
            values[key] = raw
        index += 1
    return values


def split_workflow_paths(raw: str) -> set[str]:
    paths = {item for item in raw.split() if item}
    if not paths:
        raise ValueError("release workflow path input must not be empty")
    return paths


def require_release_paths_exist(paths: set[str], label: str) -> None:
    tracked = tracked_release_paths()
    for relative in sorted(paths):
        if relative.startswith("/") or ".." in Path(relative).parts:
            raise ValueError(f"release {label} contains unsafe path {relative}")
        if relative == ".git" or relative.startswith(".git/"):
            raise ValueError(f"release {label} must not include git internals")
        if not (ROOT / relative).exists():
            raise ValueError(f"release {label} path does not exist: {relative}")
        if tracked is not None and not release_path_is_tracked(relative, tracked):
            raise ValueError(f"release {label} path has no tracked content: {relative}")


def tracked_release_paths() -> set[str] | None:
    if not (ROOT / ".git").exists():
        return None
    completed = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError(f"cannot inspect tracked release paths: {completed.stderr.strip()}")
    return {line for line in completed.stdout.splitlines() if line}


def release_path_is_tracked(relative: str, tracked: set[str]) -> bool:
    return relative in tracked or any(path.startswith(f"{relative}/") for path in tracked)


def validate_claude_bridge(archive_paths: set[str], runtime_paths: set[str]) -> None:
    bridge_root = ROOT / CLAUDE_BRIDGE_ROOT
    bridge_path = ROOT / CLAUDE_BRIDGE_PATH
    try:
        root_info = bridge_root.lstat()
    except OSError as exc:
        raise ValueError(f"Claude bridge root cannot be inspected: {exc}") from exc
    if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
        raise ValueError("Claude bridge root must be a real directory")
    entries = sorted(path.name for path in bridge_root.iterdir())
    if entries != ["CLAUDE.md"]:
        raise ValueError("Claude bridge root must contain only CLAUDE.md")
    try:
        file_info = bridge_path.lstat()
    except OSError as exc:
        raise ValueError(f"Claude bridge file cannot be inspected: {exc}") from exc
    if not stat.S_ISREG(file_info.st_mode) or stat.S_ISLNK(file_info.st_mode):
        raise ValueError("Claude bridge must be a regular non-symlink file")
    if bridge_path.read_bytes() != CLAUDE_BRIDGE_BYTES:
        raise ValueError("Claude bridge bytes must equal @../AGENTS.md newline")
    for label, paths in (("archive_paths", archive_paths), ("runtime_paths", runtime_paths)):
        if CLAUDE_BRIDGE_ROOT not in paths:
            raise ValueError(f"release {label} must include the Claude bridge root")
        if CLAUDE_BRIDGE_TARGET not in paths:
            raise ValueError(f"release {label} must include the Claude bridge target")


def contract_runtime_required_paths(manifest: dict[str, Any], contract: dict[str, Any]) -> set[str]:
    required = {"README.md", "LICENSE", "VERSION", "build", "cli-tools", "config"}
    for key in ("source_root", "profile_root"):
        value = manifest.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"manifest {key} must be a path string")
        required.add(value)
    builder = manifest.get("nddev_builder")
    if not isinstance(builder, dict) or not isinstance(builder.get("source"), str):
        raise ValueError("manifest nddev_builder.source missing")
    required.add(Path(builder["source"]).parts[0])
    compatibility = manifest.get("runtime_compatibility")
    if not isinstance(compatibility, dict):
        raise ValueError("manifest runtime_compatibility missing")
    for key in ("baseline_ref", "version_ref"):
        value = compatibility.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"manifest runtime_compatibility.{key} missing")
        required.add(Path(value).parts[0])
    for key in ("source_root", "profile_root"):
        value = contract.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"contract {key} must be a path string")
        required.add(value)
    marketplace = contract.get("plugin_marketplace")
    if not isinstance(marketplace, dict):
        raise ValueError("contract plugin_marketplace missing")
    for key in ("plugin_manifest", "marketplace_manifest", "marketplace_index"):
        value = marketplace.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"contract plugin_marketplace.{key} missing")
        required.add(Path(value).parts[0])
    return required


def setup_ids() -> list[str]:
    ids: list[str] = []
    for setup_id in SETUP_ORDER:
        setup_json = ROOT / "setups" / setup_id / "setup.json"
        setup = load_json(setup_json)
        ids.append(str(setup["id"]))
        if setup_json.parent.name != setup["id"]:
            raise ValueError(f"{setup_json}: directory name and id differ")
        if setup.get("default_profile") != "full-auto":
            raise ValueError(f"{setup_json}: default_profile must be full-auto")
        capabilities = setup.get("managed_capabilities")
        expected_capabilities = {
            "memory": True,
            "subagents": True,
            "web_fetch": True,
            "lsp_tools": True,
            "write_file": True,
            "tool_search": True,
        }
        if capabilities != expected_capabilities:
            raise ValueError(f"{setup_json}: managed capabilities mismatch")
    return ids


def profile_ids() -> list[str]:
    ids: list[str] = []
    expected = {
        "full-auto": ("always-approve", "off"),
        "safe": ("ask", "strict"),
    }
    for profile_id in PROFILE_ORDER:
        profile_json = ROOT / "profiles" / profile_id / "profile.json"
        profile = load_json(profile_json)
        ids.append(str(profile["id"]))
        if profile_json.parent.name != profile["id"]:
            raise ValueError(f"{profile_json}: directory name and id differ")
        if (profile.get("permission_mode"), profile.get("sandbox_profile")) != expected[profile_id]:
            raise ValueError(f"{profile_json}: permission/sandbox mapping mismatch")
        if profile.get("managed_permission_rules") is not False:
            raise ValueError(f"{profile_json}: managed_permission_rules must be false")
    return ids


def load_manager_module() -> Any:
    path = ROOT / "cli-tools" / "nddev_grok_build.py"
    spec = importlib.util.spec_from_file_location("nddev_grok_build_public_validate", path)
    if spec is None or spec.loader is None:
        raise ValueError("cannot import nddev_grok_build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_manager_source() -> None:
    source = (ROOT / "cli-tools" / "nddev_grok_build.py").read_text(encoding="utf-8")
    for marker in FORBIDDEN_MANAGER_SOURCE_MARKERS:
        if marker in source:
            raise ValueError(f"manager source exposes forbidden test switch marker: {marker}")
    for marker in (
        "import ctypes",
        "O_NOFOLLOW",
        "fcntl.flock",
        "LOCK_PARENT_HELD_MODE = 0o500",
        "IMMUTABLE_EXEC_MODE = 0o500",
        'LOCK_DIR_NAME = "locks"',
        'PRODUCT_LOCK_FILE_NAME = "global.lock"',
        'TARGET_LOCK_ROOT_NAME = "target-locks"',
        "BOOTSTRAP_LOCK_NAMESPACE",
        "RENAME_EXCL_DARWIN",
        "RENAME_NOREPLACE_LINUX",
        "def rename_no_replace(",
        "def write_atomic_anchor(",
        "def bootstrap_system_root()",
        "def acquire_bootstrap_lock(",
        "def read_lifecycle_payload(",
        "def validate_launch_workspace(",
        'launch_parser.add_argument("--workspace")',
        "cwd=launch_workspace",
        "while offset < len(data)",
        "binding write made no progress",
    ):
        if marker not in source:
            raise ValueError(f"manager source is missing lock invariant marker: {marker}")


def expect_manager_error(manager: Any, callback: Any, expected: str) -> None:
    try:
        callback()
    except manager.GrokBuildSetupError as exc:
        if expected not in str(exc):
            raise ValueError(f"unexpected manager error: {exc}") from exc
        return
    raise ValueError(f"expected manager error containing {expected!r}")


def install_stub_software(manager: Any, target: Path, body: bytes) -> str:
    for directory in (
        manager.software_container(target),
        manager.software_root(target),
        manager.software_versions_dir(target),
        manager.software_version_dir(target),
        manager.managed_grok_path(target).parent,
    ):
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(manager.OWNER_DIRECTORY_MODE)
    digest = hashlib.sha256(body).hexdigest()
    for binary in (manager.managed_grok_path(target), manager.software_tree_binary(target)):
        binary.write_bytes(body)
        binary.chmod(manager.OWNER_EXEC_MODE)
    stamp = manager.software_stamp(
        target,
        installer_source=manager.INSTALLER_URL,
        installer_sha256=manager.INSTALLER_SHA256,
        binary_sha256=digest,
        version_output=f"grok {manager.GROK_VERSION}",
    )
    manager.software_stamp_path(target).write_text(
        json.dumps(stamp, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manager.software_stamp_path(target).chmod(manager.OWNER_FILE_MODE)
    return digest


def validate_runtime_write_smoke(manager: Any, target: Path) -> None:
    body = (
        b"#!/bin/sh\n"
        b"set -eu\n"
        b"if [ \"${1:-}\" != \"--cwd\" ]; then exit 73; fi\n"
        b"if [ ! -d \"${2:-}\" ]; then exit 74; fi\n"
        b"workspace=$(cd \"$2\" && pwd -P)\n"
        b"current=$(pwd -P)\n"
        b"if [ \"$workspace\" != \"$current\" ]; then exit 75; fi\n"
        b"mkdir -p \"$HOME/.config/grok-build\"\n"
        b"mkdir -p \"$XDG_CONFIG_HOME/grok-build\"\n"
        b"mkdir -p \"$XDG_CACHE_HOME/grok-build\"\n"
        b"mkdir -p \"$XDG_DATA_HOME/grok-build\"\n"
        b"mkdir -p \"$XDG_STATE_HOME/grok-build\"\n"
        b"mkdir -p \"$TMPDIR/grok-build\"\n"
        b"mkdir -p \"$GROK_HOME/runtime-state\"\n"
        b"printf home > \"$HOME/.config/grok-build/home.txt\"\n"
        b"printf config > \"$XDG_CONFIG_HOME/grok-build/config.txt\"\n"
        b"printf cache > \"$XDG_CACHE_HOME/grok-build/cache.txt\"\n"
        b"printf data > \"$XDG_DATA_HOME/grok-build/data.txt\"\n"
        b"printf state > \"$XDG_STATE_HOME/grok-build/session.txt\"\n"
        b"printf tmp > \"$TMPDIR/grok-build/tmp.txt\"\n"
        b"printf target > \"$GROK_HOME/runtime-state/target.txt\"\n"
        b"if rm \"$GROK_HOME/.nddev-grok-build/locks/target.lock\" 2>/dev/null; then exit 70; fi\n"
        b"if rmdir \"$GROK_HOME/.nddev-grok-build/locks\" 2>/dev/null; then exit 71; fi\n"
        b"if (printf bad > \"$0\") 2>/dev/null; then exit 72; fi\n"
        b"printf ok > \"$GROK_HOME/runtime-state/result.txt\"\n"
    )
    install_stub_software(manager, target, body)
    rc = manager.launch(target, ["runtime-write"])
    if rc != 0:
        raise ValueError(f"runtime write smoke exited {rc}")
    runtime_root = target / ".nddev-grok-build-runtime"
    expected = {
        runtime_root / "home" / ".config" / "grok-build" / "home.txt": b"home",
        runtime_root / "home" / ".config" / "grok-build" / "config.txt": b"config",
        runtime_root / "home" / ".cache" / "grok-build" / "cache.txt": b"cache",
        runtime_root / "home" / ".local" / "share" / "grok-build" / "data.txt": b"data",
        runtime_root / "home" / ".local" / "state" / "grok-build" / "session.txt": b"state",
        runtime_root / "tmp" / "grok-build" / "tmp.txt": b"tmp",
        target / "runtime-state" / "target.txt": b"target",
        target / "runtime-state" / "result.txt": b"ok",
    }
    for path, content in expected.items():
        if path.read_bytes() != content:
            raise ValueError(f"runtime write smoke did not write expected state: {path}")
    if stat.S_IMODE(manager.managed_control_dir(target).lstat().st_mode) != manager.OWNER_DIRECTORY_MODE:
        raise ValueError("control root must stay writable after launch")
    if stat.S_IMODE(manager.lock_parent_dir(target).lstat().st_mode) != manager.OWNER_DIRECTORY_MODE:
        raise ValueError("lock parent was not restored after launch")
    if manager.launch_image_dir(target).exists():
        raise ValueError("launch image directory was not pruned after launch")


def target_managed_bytes(manager: Any, target: Path) -> dict[str, bytes | None]:
    stamp = manager.read_stamp(target)
    if stamp is None:
        raise ValueError("expected managed target")
    paths = sorted({*stamp["managed_files"], manager.STAMP_NAME})
    values: dict[str, bytes | None] = {}
    for relative in paths:
        path = manager.safe_target_path(target, relative)
        values[relative] = path.read_bytes() if path.exists() else None
    return values


def assert_target_bytes(manager: Any, target: Path, expected: dict[str, bytes | None]) -> None:
    if target_managed_bytes(manager, target) != expected:
        raise ValueError("restore failure did not preserve byte-identical managed state")
    status = manager.status_payload(target)
    if status["drift"]:
        raise ValueError("restore failure left managed drift")


def write_backup_envelope(manager: Any, envelope_path: Path, envelope: dict[str, Any]) -> None:
    envelope_path.write_text(
        json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    envelope_path.chmod(manager.OWNER_FILE_MODE)


def encoded_json(value: dict[str, Any]) -> str:
    return base64.b64encode(
        (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    ).decode("ascii")


def validate_restore_backup_smokes(manager: Any, target: Path, setup: dict[str, Any]) -> None:
    safe_profile = manager.load_profile("safe")
    switch = manager.write_setup(target, setup, safe_profile, require_existing=True)
    slot = switch["backup_slot"]
    if slot is None:
        raise ValueError("profile switch did not create a backup")
    envelope_path = manager.backup_envelope_path(target, int(slot))
    original_bytes = envelope_path.read_bytes()

    def variant(mutator: Any, expected: str) -> None:
        envelope = json.loads(original_bytes.decode("utf-8"))
        mutator(envelope)
        write_backup_envelope(manager, envelope_path, envelope)
        before = target_managed_bytes(manager, target)
        expect_manager_error(manager, lambda: manager.restore_backup(target, int(slot)), expected)
        assert_target_bytes(manager, target, before)
        envelope_path.write_bytes(original_bytes)
        envelope_path.chmod(manager.OWNER_FILE_MODE)

    def corrupt_base64(envelope: dict[str, Any]) -> None:
        envelope["files"]["config.toml"] = "!!!!"

    def corrupt_digest(envelope: dict[str, Any]) -> None:
        payload = base64.b64decode(
            envelope["files"]["config.toml"].encode("ascii"), validate=True
        )
        marker = manager.MANAGED_BEGIN.encode("utf-8")
        if marker not in payload:
            raise ValueError("config.toml backup is missing the managed marker")
        envelope["files"]["config.toml"] = base64.b64encode(
            payload.replace(marker, marker + b"\n# corrupt", 1)
        ).decode("ascii")

    def missing_path(envelope: dict[str, Any]) -> None:
        del envelope["files"]["config.toml"]

    def extra_path(envelope: dict[str, Any]) -> None:
        envelope["files"]["unmanaged.txt"] = base64.b64encode(b"extra").decode("ascii")

    def wrong_scalar(envelope: dict[str, Any]) -> None:
        envelope["slot"] = str(slot)

    def extra_stamp_path(envelope: dict[str, Any]) -> None:
        stamp = json.loads(
            base64.b64decode(
                envelope["files"][manager.STAMP_NAME].encode("ascii"), validate=True
            ).decode("utf-8")
        )
        payload = b"managed by forged stamp\n"
        stamp["managed_files"]["unmanaged.txt"] = hashlib.sha256(payload).hexdigest()
        envelope["files"][manager.STAMP_NAME] = encoded_json(stamp)
        envelope["files"]["unmanaged.txt"] = base64.b64encode(payload).decode("ascii")

    variant(corrupt_base64, "valid base64")
    variant(corrupt_digest, "digest mismatch")
    variant(missing_path, "file set")
    variant(extra_path, "file set")
    variant(wrong_scalar, "slot is invalid")
    variant(extra_stamp_path, "managed path set")

    restored = manager.restore_backup(target, int(slot))
    if restored["profile_id"] != "full-auto":
        raise ValueError("valid restore did not restore the backed-up profile")
    if manager.status_payload(target)["drift"]:
        raise ValueError("valid restore left managed drift")


def expect_manager_main_error(manager: Any, argv: list[str], expected: str) -> None:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        rc = manager.main(argv)
    if rc != 2:
        raise ValueError(f"expected manager rc=2, got {rc}")
    payload = json.loads(output.getvalue())
    if expected not in str(payload.get("error", "")):
        raise ValueError(f"unexpected manager JSON error: {payload}")


def close_fds_except(keep: set[int]) -> None:
    try:
        limit = int(os.sysconf("SC_OPEN_MAX"))
    except (AttributeError, OSError, ValueError):
        limit = 256
    start = 3
    for fd in sorted(item for item in keep if item >= 3):
        if start < fd:
            os.closerange(start, fd)
        start = fd + 1
    if start < limit:
        os.closerange(start, limit)


def send_child_result(write_fd: int, payload: dict[str, Any]) -> None:
    data = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
    os.write(write_fd, data)


def read_child_result(read_fd: int, pid: int, *, wait: bool = True) -> dict[str, Any]:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(read_fd, 65536)
        if not chunk:
            break
        chunks.append(chunk)
        if b"\n" in chunk:
            break
    if wait:
        _, status = os.waitpid(pid, 0)
        if status != 0:
            raise ValueError(f"child process exited with status {status}")
    payload = json.loads(b"".join(chunks).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("child result must be a JSON object")
    return payload


def fork_expect_manager_error(manager: Any, callback: Any, expected: str) -> None:
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            close_fds_except({write_fd})
            try:
                callback()
            except manager.GrokBuildSetupError as exc:
                send_child_result(write_fd, {"ok": expected in str(exc), "error": str(exc)})
            except BaseException as exc:
                send_child_result(write_fd, {"ok": False, "error": repr(exc)})
            else:
                send_child_result(write_fd, {"ok": False, "error": "operation unexpectedly succeeded"})
        finally:
            os._exit(0)
    os.close(write_fd)
    try:
        payload = read_child_result(read_fd, pid)
    finally:
        os.close(read_fd)
    if payload.get("ok") is not True:
        raise ValueError(f"unexpected forked manager result: {payload}")


def snapshot_file_digest(path: Path, size: int) -> str | None:
    if size > METADATA_MAX_BYTES:
        return None
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > METADATA_MAX_BYTES:
                return None
            digest.update(chunk)
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def snapshot_path(path: Path) -> dict[str, Any]:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {"exists": False}
    mode = info.st_mode
    if stat.S_ISDIR(mode):
        kind = "directory"
        digest = None
        link_target = None
    elif stat.S_ISREG(mode):
        kind = "regular"
        digest = snapshot_file_digest(path, info.st_size)
        link_target = None
    elif stat.S_ISLNK(mode):
        kind = "symlink"
        digest = None
        link_target = os.readlink(path)
    else:
        kind = "other"
        digest = None
        link_target = None
    return {
        "exists": True,
        "kind": kind,
        "mode": stat.S_IMODE(mode),
        "uid": info.st_uid,
        "gid": info.st_gid,
        "nlink": info.st_nlink,
        "dev": info.st_dev,
        "ino": info.st_ino,
        "size": info.st_size,
        "sha256": digest,
        "link_target": link_target,
    }


def bootstrap_artifact_snapshot(manager: Any) -> Any:
    system_root = Path("/tmp").resolve(strict=True)
    root = manager.bootstrap_product_root_path(system_root)
    root_snapshot = snapshot_path(root)
    if root_snapshot.get("kind") != "directory":
        return {"root": root_snapshot, "entries": ()}
    entries: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        entries.append((path.name, snapshot_path(path)))
    return {"root": root_snapshot, "entries": tuple(entries)}


@contextlib.contextmanager
def isolated_bootstrap_root(manager: Any):
    before = bootstrap_artifact_snapshot(manager)
    original = manager.bootstrap_system_root
    with tempfile.TemporaryDirectory(prefix="nddev-grok-build-lock-root-") as tmp_raw:
        root = Path(tmp_raw) / "system-tmp"
        root.mkdir(mode=0o700)
        root.chmod(0o1777)

        def resolver() -> Path:
            info = root.lstat()
            if not stat.S_ISDIR(info.st_mode) or not (info.st_mode & stat.S_ISVTX):
                raise ValueError("injected bootstrap root is not sticky")
            return root

        manager.bootstrap_system_root = resolver
        try:
            yield root
        finally:
            manager.bootstrap_system_root = original
    after = bootstrap_artifact_snapshot(manager)
    if after != before:
        raise ValueError("public validator changed the real system bootstrap lock root")


def validate_bootstrap_handover_smoke(manager: Any, target: Path) -> None:
    identity = manager.bootstrap_target_identity(target)
    descriptor = manager.acquire_bootstrap_lock(target)
    path = manager.bootstrap_lock_path(identity)
    initial = path.lstat()
    start_read, start_write = os.pipe()
    stop_read, stop_write = os.pipe()
    result_read, result_write = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(start_write)
        os.close(stop_write)
        os.close(result_read)
        try:
            close_fds_except({start_read, stop_read, result_write})
            os.read(start_read, 1)
            child_descriptor = manager.acquire_bootstrap_lock(target)
            child_info = os.fstat(child_descriptor)
            current = path.lstat()
            send_child_result(
                result_write,
                {
                    "ok": True,
                    "fd": [child_info.st_dev, child_info.st_ino],
                    "path": [current.st_dev, current.st_ino],
                },
            )
            os.read(stop_read, 1)
            manager.release_bootstrap_lock(child_descriptor)
        except BaseException as exc:
            send_child_result(result_write, {"ok": False, "error": repr(exc)})
        finally:
            os._exit(0)
    os.close(start_read)
    os.close(stop_read)
    os.close(result_write)
    try:
        manager.release_bootstrap_lock(descriptor)
        os.write(start_write, b"x")
        os.close(start_write)
        payload = read_child_result(result_read, pid, wait=False)
        if payload.get("ok") is not True:
            raise ValueError(f"bootstrap handover child failed: {payload}")
        expected_inode = [initial.st_dev, initial.st_ino]
        if payload.get("fd") != expected_inode or payload.get("path") != expected_inode:
            raise ValueError("bootstrap lock handover did not keep the persistent inode")
        fork_expect_manager_error(
            manager,
            lambda: manager.release_bootstrap_lock(manager.acquire_bootstrap_lock(target)),
            "target is locked",
        )
    finally:
        with contextlib.suppress(OSError):
            os.write(stop_write, b"x")
        with contextlib.suppress(OSError):
            os.close(stop_write)
        with contextlib.suppress(OSError):
            os.close(result_read)
        with contextlib.suppress(ChildProcessError):
            os.waitpid(pid, 0)
    final_descriptor = manager.acquire_bootstrap_lock(target)
    try:
        final = path.lstat()
        if (final.st_dev, final.st_ino) != (initial.st_dev, initial.st_ino):
            raise ValueError("bootstrap lock inode changed after handover")
    finally:
        manager.release_bootstrap_lock(final_descriptor)


def validate_bootstrap_binding_smokes(manager: Any, target: Path) -> None:
    identity = manager.bootstrap_target_identity(target)
    path = manager.bootstrap_lock_path(identity)
    product = manager.acquire_product_lock(create=True, exclusive=True)
    if product is None:
        raise ValueError("product lock was not created for bootstrap binding smoke")
    manager.release_product_lock(product)

    def write_raw_binding(data: bytes) -> None:
        path.parent.mkdir(mode=manager.OWNER_DIRECTORY_MODE, parents=True, exist_ok=True)
        path.parent.chmod(manager.OWNER_DIRECTORY_MODE)
        path.write_bytes(data)
        path.chmod(manager.OWNER_FILE_MODE)

    variants = (
        (b"{not json\n", "invalid JSON"),
        (b"[]\n", "JSON object"),
        (
            manager.canonical_json(
                manager.bootstrap_lock_binding(
                    str(target.parent.resolve(strict=True) / "other-grok-home")
                )
            ),
            "does not match",
        ),
    )
    for payload, expected in variants:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        write_raw_binding(payload)
        expect_manager_error(manager, lambda: manager.acquire_bootstrap_lock(target), expected)

    with contextlib.suppress(FileNotFoundError):
        path.unlink()
    original_write = manager.os.write
    writes: list[int] = []

    def short_write(descriptor: int, data: bytes) -> int:
        amount = 1 if data else 0
        written = original_write(descriptor, data[:amount])
        writes.append(written)
        return written

    try:
        manager.os.write = short_write
        descriptor = manager.acquire_bootstrap_lock(target)
    finally:
        manager.os.write = original_write
    try:
        if len(writes) <= 1:
            raise ValueError("bootstrap lock short-write regression did not force a write loop")
        expected_bytes = manager.expected_bootstrap_lock_binding_bytes(identity)
        with path.open("rb") as handle:
            if handle.read() != expected_bytes:
                raise ValueError("bootstrap lock short-write loop produced an invalid binding")
    finally:
        manager.release_bootstrap_lock(descriptor)

    with contextlib.suppress(FileNotFoundError):
        path.unlink()
    original_write = manager.os.write

    def no_progress(_descriptor: int, _data: bytes) -> int:
        return 0

    try:
        manager.os.write = no_progress
        expect_manager_error(
            manager, lambda: manager.acquire_bootstrap_lock(target), "made no progress"
        )
    finally:
        manager.os.write = original_write
    descriptor = manager.acquire_bootstrap_lock(target)
    manager.release_bootstrap_lock(descriptor)


def validate_no_replace_publication_smoke(manager: Any) -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-grok-build-no-replace-") as tmp_raw:
        tmp = Path(tmp_raw)
        tmp.chmod(manager.OWNER_DIRECTORY_MODE)
        path = tmp / manager.PRODUCT_LOCK_FILE_NAME
        data = manager.expected_product_lock_binding_bytes()
        if manager.write_atomic_anchor(path, data, manager.OWNER_FILE_MODE, "validator product lock") is not True:
            raise ValueError("initial no-replace publication did not publish")
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("no-replace publication must create one regular final inode")
        if stat.S_IMODE(info.st_mode) != manager.OWNER_FILE_MODE:
            raise ValueError("no-replace publication mode mismatch")
        if path.read_bytes() != data:
            raise ValueError("no-replace publication bytes changed")
        if manager.write_atomic_anchor(
            path, b"{\"unexpected\":true}\n", manager.OWNER_FILE_MODE, "validator product lock"
        ) is not False:
            raise ValueError("no-replace publication overwrote an existing final anchor")
        if path.read_bytes() != data:
            raise ValueError("no-replace EEXIST path changed the final anchor")
        if any(item.name.startswith(f".{path.name}.nddev.tmp.") for item in tmp.iterdir()):
            raise ValueError("no-replace EEXIST path left a publication temp file")


def validate_fetch_error_smokes(manager: Any) -> None:
    original_urlopen = manager.urllib.request.urlopen

    class BadResponse:
        headers = {"Content-Length": "not-an-int"}

        def __enter__(self) -> "BadResponse":
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            return False

        def read(self, size: int) -> bytes:
            return b""

    try:
        with tempfile.TemporaryDirectory(prefix="nddev-grok-build-fetch-") as tmp_raw:
            target = Path(tmp_raw) / "grok-home"

            def offline(*args: Any, **kwargs: Any) -> Any:
                raise OSError("offline")

            manager.urllib.request.urlopen = offline
            expect_manager_main_error(
                manager,
                ["install-cli", "--target", str(target), "--json"],
                "fetch failed",
            )
            if target.exists():
                raise ValueError("failed install-cli did not remove the newly created target")

            manager.urllib.request.urlopen = lambda *args, **kwargs: BadResponse()
            expect_manager_main_error(
                manager,
                ["install-cli", "--target", str(target), "--json"],
                "Content-Length",
            )
            if target.exists():
                raise ValueError("failed install-cli did not remove the newly created target")

            def interrupted(*args: Any, **kwargs: Any) -> Any:
                raise KeyboardInterrupt

            manager.urllib.request.urlopen = interrupted
            try:
                manager.read_pinned_installer()
            except KeyboardInterrupt:
                pass
            except BaseException as exc:
                raise ValueError("installer fetch must preserve KeyboardInterrupt") from exc
            else:
                raise ValueError("installer fetch did not raise KeyboardInterrupt")
    finally:
        manager.urllib.request.urlopen = original_urlopen


def validate_adversarial_smokes(manager: Any) -> None:
    setup = manager.load_setup(manager.DEFAULT_SETUP_ID)
    profile = manager.load_profile(manager.DEFAULT_PROFILE_ID)
    with tempfile.TemporaryDirectory(prefix="nddev-grok-build-public-") as tmp_raw:
        tmp = Path(tmp_raw)
        bad_target = tmp / "bad-mode"
        bad_target.mkdir(mode=0o700)
        bad_target.chmod(0o777)
        try:
            expect_manager_error(
                manager,
                lambda: manager.status_payload(bad_target),
                "target must have mode 0700",
            )
        finally:
            bad_target.chmod(0o700)

        target = tmp / "grok-home"
        target.mkdir(mode=0o700)
        sibling_lock = tmp / ".grok-home.nddev-grok-build.lock"
        sibling_backups = tmp / ".grok-home.nddev-grok-build-backups"
        sibling_lock.mkdir(mode=0o700)
        sibling_backups.mkdir(mode=0o700)
        (sibling_backups / "marker").write_text("must not be read\n", encoding="utf-8")
        manager.write_setup(target, setup, profile)
        if not sibling_lock.is_dir() or not sibling_backups.is_dir():
            raise ValueError("manager touched precreated sibling lock/backup state")
        status = manager.status_payload(target)
        if status["launchable"] or status.get("software_current") is not False:
            raise ValueError("status launchable must be false without current software")

        validate_bootstrap_handover_smoke(manager, target)
        validate_bootstrap_binding_smokes(manager, target)
        validate_restore_backup_smokes(manager, target, setup)

        denied = (
            ["update"],
            ["setup"],
            ["login"],
            ["plugin", "install", "nddev-builder"],
            ["plugin", "marketplace", "add", "local"],
            ["mcp", "add", "server"],
        )
        for child_args in denied:
            expect_manager_error(
                manager,
                lambda args=child_args: manager.launch(target, list(args)),
                "managed-state mutation",
            )

        original = (
            b"#!/bin/sh\n"
            b"printf 'original\\n' > \"$GROK_HOME/stable-fd-result.txt\"\n"
        )
        replacement = (
            b"#!/bin/sh\n"
            b"printf 'replacement\\n' > \"$GROK_HOME/stable-fd-result.txt\"\n"
        )
        validate_runtime_write_smoke(manager, target)
        original_digest = install_stub_software(manager, target, original)
        original_popen = manager.subprocess.Popen
        explicit_workspace = tmp / "project-workspace"
        explicit_workspace.mkdir(mode=0o700)
        explicit_workspace = explicit_workspace.resolve(strict=True)

        class FakePopen:
            def __init__(self, command: list[str], **kwargs: Any) -> None:
                control = manager.managed_control_dir(target)
                lock_parent = manager.lock_parent_dir(target)
                renamed_lock_parent = lock_parent.with_name(f"{lock_parent.name}.renamed")
                lock = manager.lock_path(target)
                control_mode = stat.S_IMODE(control.lstat().st_mode)
                if control_mode != manager.OWNER_DIRECTORY_MODE:
                    raise ValueError("launch made the control root non-writable")
                lock_parent_mode = stat.S_IMODE(lock_parent.lstat().st_mode)
                if lock_parent_mode != manager.LOCK_PARENT_HELD_MODE:
                    raise ValueError("launch did not make the lock parent non-writable")
                lock_info = lock.lstat()
                if not stat.S_ISREG(lock_info.st_mode):
                    raise ValueError("launch lock must be a regular file")
                if stat.S_IMODE(lock_info.st_mode) != manager.OWNER_FILE_MODE:
                    raise ValueError("launch lock file must have mode 0600")
                try:
                    lock.unlink()
                except PermissionError:
                    pass
                else:
                    raise ValueError("launch child could unlink the held lock file")
                try:
                    lock_parent.rmdir()
                except OSError:
                    pass
                else:
                    raise ValueError("launch child could remove the held lock parent")
                lock_parent.rename(renamed_lock_parent)
                self.renamed_lock_parent = renamed_lock_parent
                fork_expect_manager_error(
                    manager,
                    lambda: manager.remove_setup(target),
                    "target is locked",
                )
                safe_profile = manager.load_profile("safe")
                fork_expect_manager_error(
                    manager,
                    lambda: manager.write_setup(
                        target, setup, safe_profile, require_existing=True
                    ),
                    "target is locked",
                )
                fork_expect_manager_error(
                    manager,
                    lambda: manager.write_setup(target, setup, profile),
                    "target is locked",
                )
                launch_image = Path(command[0])
                if command[1:3] != ["--cwd", str(explicit_workspace)]:
                    raise ValueError("launch did not pass native --cwd bound to the workspace")
                if Path(kwargs.get("cwd", "")).resolve(strict=True) != explicit_workspace:
                    raise ValueError("launch child cwd was not bound to the workspace")
                if launch_image.parent.resolve() != manager.launch_image_dir(target).resolve():
                    raise ValueError("launch did not use a private target-internal launch image")
                if stat.S_IMODE(launch_image.parent.lstat().st_mode) != manager.LOCK_PARENT_HELD_MODE:
                    raise ValueError("launch image directory must be non-writable during launch")
                if stat.S_IMODE(launch_image.lstat().st_mode) != manager.IMMUTABLE_EXEC_MODE:
                    raise ValueError("launch image must use immutable executable mode")
                if kwargs.get("close_fds") is not True:
                    raise ValueError("launch must close ambient file descriptors")
                launched = launch_image.read_bytes()
                if hashlib.sha256(launched).hexdigest() != original_digest:
                    raise ValueError("launch image does not match the verified software stamp")
                manager.managed_grok_path(target).write_bytes(replacement)
                manager.managed_grok_path(target).chmod(manager.OWNER_EXEC_MODE)
                self.returncode = 0

            def wait(self) -> int:
                renamed_lock = self.renamed_lock_parent / manager.LOCK_FILE_NAME
                if not renamed_lock.is_file():
                    raise ValueError("renamed launch lock was released before child exit")
                self.renamed_lock_parent.rename(manager.lock_parent_dir(target))
                return self.returncode

            def kill(self) -> None:
                self.returncode = -9

        try:
            manager.subprocess.Popen = FakePopen
            if manager.launch(target, ["doctor"], workspace=str(explicit_workspace)) != 0:
                raise ValueError("stubbed launch did not return success")
        finally:
            manager.subprocess.Popen = original_popen
        if stat.S_IMODE(manager.lock_parent_dir(target).lstat().st_mode) != manager.OWNER_DIRECTORY_MODE:
            raise ValueError("launch lock parent was not restored")
        if manager.launch_image_dir(target).exists():
            raise ValueError("launch image directory was not removed")

        install_stub_software(manager, target, original)

        class MutatingPopen:
            def __init__(self, command: list[str], **kwargs: Any) -> None:
                launch_image = Path(command[0])
                try:
                    launch_image.write_bytes(replacement)
                except PermissionError:
                    pass
                else:
                    raise ValueError("ordinary launch image replacement unexpectedly succeeded")
                launch_image.parent.chmod(manager.OWNER_DIRECTORY_MODE)
                launch_image.chmod(manager.OWNER_EXEC_MODE)
                launch_image.write_bytes(replacement)
                self.returncode = 0
                self.killed = False

            def wait(self) -> int:
                return self.returncode

            def kill(self) -> None:
                self.killed = True
                self.returncode = -9

        try:
            manager.subprocess.Popen = MutatingPopen
            expect_manager_error(
                manager,
                lambda: manager.launch(target, ["doctor"]),
                "launch image digest changed",
            )
        finally:
            manager.subprocess.Popen = original_popen

    sticky_parent = Path("/tmp")
    if sticky_parent.exists() and sticky_parent.stat().st_mode & stat.S_ISVTX:
        sticky_target = Path(tempfile.mkdtemp(prefix="nddev-grok-build-", dir=str(sticky_parent)))
        try:
            sticky_target.chmod(0o700)
            manager.write_setup(sticky_target, setup, profile)
            sticky_status = manager.status_payload(sticky_target)
            if not sticky_status["managed"]:
                raise ValueError("0700 target under sticky temp parent was not accepted")
        finally:
            shutil.rmtree(sticky_target, ignore_errors=True)


def validate_builder_toolkit(build_version: str) -> None:
    marketplace_path = ROOT / "builder" / "nddev-builder" / ".grok-plugin" / "marketplace.json"
    plugin_root = ROOT / "builder" / "nddev-builder" / "plugins" / "nddev-builder"
    marketplace = load_json(marketplace_path)
    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list) or len(plugins) != 1:
        raise ValueError("marketplace must publish exactly the nddev-builder plugin")
    source = plugins[0].get("source")
    if not isinstance(source, dict) or source.get("type") != "local":
        raise ValueError("marketplace plugin source must be local")
    source_path = source.get("path")
    if not isinstance(source_path, str):
        raise ValueError("marketplace plugin source path must be a string")
    resolved_source = (marketplace_path.parent / source_path).resolve()
    if resolved_source != plugin_root.resolve() or not resolved_source.is_dir():
        raise ValueError("marketplace local source path does not resolve to the plugin root")

    plugin_manifest = load_json(plugin_root / "plugin.json")
    if plugin_manifest.get("name") != "nddev-builder":
        raise ValueError("builder plugin manifest name mismatch")
    if plugin_manifest.get("version") != build_version:
        raise ValueError("builder plugin version must match public build version")

    for path in plugin_root.rglob("*"):
        if path.is_dir():
            continue
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"builder payload is not a regular file: {path.relative_to(ROOT)}")
        if stat.S_IMODE(info.st_mode) & 0o111:
            raise ValueError(f"builder payload must not ship executable files: {path.relative_to(ROOT)}")
        if path.suffix.lower() in {".bin", ".exe", ".dmg", ".pkg", ".deb", ".rpm", ".zip", ".tgz"}:
            raise ValueError(f"builder payload must not ship binary/runtime archives: {path.relative_to(ROOT)}")

    for skill in BUILDER_SKILLS:
        skill_path = plugin_root / "skills" / skill / "SKILL.md"
        if not skill_path.is_file():
            raise ValueError(f"missing builder skill {skill_path.relative_to(ROOT)}")
        text = skill_path.read_text(encoding="utf-8")
        if f"name: {skill}" not in text:
            raise ValueError(f"{skill_path.relative_to(ROOT)}: frontmatter name mismatch")
        validate_skill_local_references(plugin_root, skill_path, text)

    entry = (plugin_root / "skills" / "nddev-builder" / "SKILL.md").read_text(encoding="utf-8")
    for reference in ("references/native-surfaces.md", "references/validation-workflows.md"):
        if reference not in entry:
            raise ValueError(f"entry builder skill does not route reference {reference}")
        if not (plugin_root / "skills" / "nddev-builder" / reference).is_file():
            raise ValueError(f"missing routed reference {reference}")

    agent = (plugin_root / "agents" / "nddev-builder.md").read_text(encoding="utf-8")
    if "\ntools:" in agent or "mcpInheritance: none" in agent:
        raise ValueError("builder agent must inherit full session tools and MCP capability")

    index = load_json(ROOT / "builder" / "nddev-builder" / ".grok-plugin" / "plugin-index.json")
    indexed_skills = {
        item.get("name")
        for item in index["plugins"]["nddev-builder"]["components"]["skills"]
        if isinstance(item, dict)
    }
    if indexed_skills != BUILDER_SKILLS:
        raise ValueError("plugin-index skill inventory does not match builder skill directories")


def validate_workflows() -> None:
    workflow_root = ROOT / ".github" / "workflows"
    for filename, workflow in REQUIRED_WORKFLOWS.items():
        path = workflow_root / filename
        if not path.is_file():
            raise ValueError(f"missing workflow {path.relative_to(ROOT)}")
        expected = (
            f"uses: NDDev-it-com/ci-workflows/{workflow}@{SHARED_CI_COMMIT} # {SHARED_CI_VERSION}"
        )
        text = path.read_text(encoding="utf-8")
        if text.count(expected) != 1:
            raise ValueError(f"{filename}: missing exact shared CI caller")


def validate_release_workflow(manifest: dict[str, Any], contract: dict[str, Any]) -> None:
    path = ROOT / ".github" / "workflows" / "release.yml"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    expected_uses = (
        "uses: "
        f"NDDev-it-com/ci-workflows/.github/workflows/release-supply-chain.yml@{SHARED_CI_COMMIT} "
        f"# {SHARED_CI_VERSION}"
    )
    if text.count(expected_uses) != 1:
        raise ValueError("release workflow must call the exact shared release-supply-chain pin")
    if '      - "[0-9]+.[0-9]+.[0-9]+"' not in text:
        raise ValueError("release workflow must publish stable numeric tags")
    permissions = parse_workflow_mapping(lines, "permissions", indent=4)
    if permissions != RELEASE_PERMISSIONS:
        raise ValueError("release workflow job permissions mismatch")
    inputs = parse_workflow_mapping(lines, "with", indent=4)
    if inputs.get("version") != "${{ github.ref_name }}":
        raise ValueError("release workflow version input must use github.ref_name")
    if inputs.get("package_name") != "nddev-grok-build-app":
        raise ValueError("release workflow package_name mismatch")
    archive_paths = split_workflow_paths(inputs.get("archive_paths", ""))
    runtime_paths = split_workflow_paths(inputs.get("runtime_paths", ""))
    require_release_paths_exist(archive_paths, "archive_paths")
    require_release_paths_exist(runtime_paths, "runtime_paths")
    missing_archive = RELEASE_ARCHIVE_REQUIRED_PATHS - archive_paths
    if missing_archive:
        raise ValueError(f"release archive_paths missing required paths: {sorted(missing_archive)}")
    if not runtime_paths <= archive_paths:
        raise ValueError("release runtime_paths must be a subset of archive_paths")
    required_runtime = contract_runtime_required_paths(manifest, contract)
    missing_runtime = required_runtime - runtime_paths
    if missing_runtime:
        raise ValueError(f"release runtime_paths missing runtime closure: {sorted(missing_runtime)}")
    validate_claude_bridge(archive_paths, runtime_paths)


def validate_skill_local_references(plugin_root: Path, skill_path: Path, text: str) -> None:
    plugin_real = plugin_root.resolve()
    for reference in re.findall(r"`([^`]+)`", text):
        if not reference.endswith(".md"):
            continue
        if not (
            reference.startswith("../")
            or reference.startswith("references/")
        ):
            continue
        candidate = (skill_path.parent / reference).resolve()
        if candidate != plugin_real and plugin_real not in candidate.parents:
            raise ValueError(
                f"{skill_path.relative_to(ROOT)}: routed reference escapes plugin root: {reference}"
            )
        if not candidate.is_file():
            raise ValueError(
                f"{skill_path.relative_to(ROOT)}: routed reference is missing: {reference}"
            )


def main(argv: list[str] | None = None) -> int:
    parse_args(argv)
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    build = load_json(ROOT / "build" / "version.json")
    manifest = load_json(ROOT / "build" / "manifest.json")
    contract = load_json(ROOT / "config" / "nddev-contract.json")
    baseline = load_json(ROOT / "references" / "grok-build-baseline.json")
    ids = setup_ids()
    profiles = profile_ids()
    if not version:
        raise ValueError("VERSION must not be empty")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## {version}" not in changelog:
        raise ValueError("CHANGELOG.md must document the current public version")
    if build.get("build_version") != version or manifest.get("build_version") != version:
        raise ValueError("build version fields are not synchronized")
    if contract.get("version_ref") != "build/version.json":
        raise ValueError("contract version_ref must point at build/version.json")
    if contract.get("manifest_ref") != "build/manifest.json":
        raise ValueError("contract manifest_ref must point at build/manifest.json")
    if "skeleton" in contract:
        raise ValueError("contract must not expose skeleton status")
    if manifest.get("setup_ids") != ids or contract["setup_system"]["setup_ids"] != ids:
        raise ValueError("setup ids are not synchronized")
    if manifest.get("profile_ids") != profiles or contract["setup_system"]["profile_ids"] != profiles:
        raise ValueError("profile ids are not synchronized")
    if manifest.get("default_setup") != "nddev-builder" or manifest.get("default_profile") != "full-auto":
        raise ValueError("manifest default setup/profile mismatch")
    backup_policy = manifest.get("backup_policy")
    if not isinstance(backup_policy, dict):
        raise ValueError("manifest backup_policy missing")
    if backup_policy.get("location") != "$GROK_HOME/.nddev-grok-build/backups":
        raise ValueError("manifest backup policy must be target-internal")
    for key in (
        "strict_envelope_validation",
        "base64_validate",
        "restored_stamp_path_set_validated",
    ):
        if backup_policy.get(key) is not True:
            raise ValueError(f"manifest backup_policy must set {key}=true")
    transaction = manifest.get("transaction_policy")
    if not isinstance(transaction, dict):
        raise ValueError("manifest transaction_policy missing")
    if transaction.get("existing_target_mode_required") != "0700":
        raise ValueError("manifest must require existing target mode 0700")
    if transaction.get("external_product_lock") != (
        "fixed resolved system temp root/.nddev-grok-build-app.uid-<uid>/global.lock"
    ):
        raise ValueError("manifest external product lock path mismatch")
    if transaction.get("external_target_lock_root") != (
        "fixed resolved system temp root/.nddev-grok-build-app.uid-<uid>/target-locks"
    ):
        raise ValueError("manifest external target lock root mismatch")
    if transaction.get("external_bootstrap_lock") != (
        "fixed resolved system temp root/.nddev-grok-build-app.uid-<uid>/"
        "target-locks/<sha256(namespace+canonical-target)>.lock"
    ):
        raise ValueError("manifest external bootstrap lock path must use fixed target lock root")
    if "/private/tmp" not in str(
        transaction.get("external_bootstrap_lock_system_root", "")
    ) or "/tmp" not in str(transaction.get("external_bootstrap_lock_system_root", "")):
        raise ValueError("manifest external bootstrap root must document macOS and Linux roots")
    if transaction.get("external_bootstrap_lock_product_root_mode") != "0700":
        raise ValueError("manifest external bootstrap product root mode mismatch")
    if transaction.get("external_bootstrap_lock_file_mode") != "0600":
        raise ValueError("manifest external bootstrap lock file mode mismatch")
    if transaction.get("external_bootstrap_lock_persistent") is not True:
        raise ValueError("manifest external bootstrap lock must be persistent")
    if transaction.get("external_bootstrap_lock_unlinked_on_release") is not False:
        raise ValueError("manifest external bootstrap lock must not be unlinked on release")
    if "complete JSON" not in str(transaction.get("external_bootstrap_lock_binding", "")):
        raise ValueError("manifest external bootstrap lock binding missing")
    if transaction.get("external_lock_atomic_no_replace") is not True:
        raise ValueError("manifest external lock must use atomic no-replace publication")
    if "renameatx_np" not in str(
        transaction.get("external_lock_no_replace_primitives", "")
    ) or "renameat2" not in str(transaction.get("external_lock_no_replace_primitives", "")):
        raise ValueError("manifest external lock primitives mismatch")
    if transaction.get("external_lock_empty_partial_malformed_fail_closed") is not True:
        raise ValueError("manifest external lock must fail closed on incomplete anchors")
    if transaction.get("external_read_only_no_create") is not True:
        raise ValueError("manifest read-only commands must not create external anchors")
    if transaction.get("external_read_only_cold_namespace_empty_required") is not True:
        raise ValueError("manifest cold read namespace rule mismatch")
    if transaction.get("external_read_only_cold_namespace_identity_retry") is not True:
        raise ValueError("manifest cold read retry rule mismatch")
    if "resolved real parent" not in str(
        transaction.get("external_bootstrap_lock_target_identity", "")
    ):
        raise ValueError("manifest external bootstrap target identity mismatch")
    if transaction.get("external_bootstrap_lock_from_ambient_tmpdir") is not False:
        raise ValueError("manifest external bootstrap lock must ignore ambient TMPDIR")
    if transaction.get("external_bootstrap_lock_child_env") is not False:
        raise ValueError("manifest external bootstrap lock must not be exposed to child env")
    if transaction.get("external_lock_acquired_before_target_inspection") is not True:
        raise ValueError("manifest external lock must be acquired before target inspection")
    if transaction.get("lock") != "$GROK_HOME/.nddev-grok-build/locks/target.lock":
        raise ValueError("manifest lock must be target-internal")
    if transaction.get("lock_parent") != "$GROK_HOME/.nddev-grok-build/locks":
        raise ValueError("manifest lock parent mismatch")
    if transaction.get("lock_type") != "persistent regular file with fcntl.flock":
        raise ValueError("manifest lock_type mismatch")
    if transaction.get("lock_file_mode") != "0600":
        raise ValueError("manifest lock file mode mismatch")
    if transaction.get("control_root_mode_while_locked") != "0700":
        raise ValueError("manifest must keep the control root writable while locked")
    if transaction.get("lock_parent_mode_while_held") != "0500":
        raise ValueError("manifest lock held parent mode mismatch")
    if transaction.get("lock_parent_mode_when_unlocked") != "0700":
        raise ValueError("manifest unlocked parent mode mismatch")
    if transaction.get("lock_held_through_launch_child") is not True:
        raise ValueError("manifest must require launch to hold the lock through child exit")
    if transaction.get("lock_crash_recovery") is not True:
        raise ValueError("manifest must declare lock crash recovery")
    if transaction.get("lock_order") != (
        "external bootstrap lock first, target-internal lock second; "
        "release target-internal first, external last"
    ):
        raise ValueError("manifest lock ordering mismatch")
    if transaction.get("launch_requires_current_software") is not True:
        raise ValueError("manifest must require current software for launch")
    for key in (
        "restore_prevalidates_backup_before_mutation",
        "restore_post_validates_clean_state",
        "restore_rollback_byte_identical_on_failure",
    ):
        if transaction.get(key) is not True:
            raise ValueError(f"manifest transaction_policy must set {key}=true")
    if transaction.get("launch_uses_verified_private_image") is not True:
        raise ValueError("manifest must require verified private launch image")
    if transaction.get("launch_image_directory") != "$GROK_HOME/.nddev-grok-build/launch-images":
        raise ValueError("manifest launch image directory mismatch")
    if transaction.get("launch_image_file_mode") != "0500":
        raise ValueError("manifest launch image file mode mismatch")
    if transaction.get("runtime_home_tmp_xdg_writable_while_locked") is not True:
        raise ValueError("manifest must keep runtime HOME/TMP/XDG writable")
    if "same user" not in str(
        transaction.get("same_uid_malicious_mutation_boundary", "")
    ).replace("-", " "):
        raise ValueError("manifest must document the same-user mutation boundary")
    if "sandbox off" not in str(
        transaction.get("same_uid_malicious_mutation_boundary", "")
    ).replace("-", " "):
        raise ValueError("manifest must document the sandbox-off same-user boundary")
    managed_state = contract.get("managed_state")
    if not isinstance(managed_state, dict):
        raise ValueError("contract managed_state missing")
    if managed_state.get("control_dir") != ".nddev-grok-build":
        raise ValueError("contract control_dir mismatch")
    if managed_state.get("existing_target_mode_required") != "0700":
        raise ValueError("contract must require existing target mode 0700")
    safety = contract.get("safety")
    if not isinstance(safety, dict):
        raise ValueError("contract safety missing")
    for key in (
        "existing_target_private_mode_required",
        "sibling_lock_and_backup_state_ignored",
        "external_bootstrap_lock_persistent",
        "external_bootstrap_lock_not_under_target_or_parent",
        "external_bootstrap_lock_uses_fixed_system_temp_root",
        "external_bootstrap_lock_ignores_ambient_tmpdir",
        "external_bootstrap_lock_json_binding",
        "external_lock_atomic_no_replace",
        "external_lock_empty_partial_malformed_fail_closed",
        "external_read_only_no_create",
        "external_read_only_cold_namespace_empty_required",
        "external_read_only_cold_namespace_identity_retry",
        "external_lock_acquired_before_target_inspection",
        "external_lock_released_after_internal_lock",
        "external_lock_not_exposed_to_child_env",
        "persistent_flock_lock_file",
        "control_root_stays_writable_while_locked",
        "lock_parent_non_writable_while_held",
        "lock_held_through_launch_child",
        "concurrent_setup_mutations_denied_while_launching",
        "legacy_sibling_backups_read_only_when_strictly_validated",
        "restore_validates_backup_envelope_before_mutation",
        "restore_validates_stamp_path_set_and_digests",
        "restore_post_validates_clean_state",
        "restore_rollback_byte_identical_on_failure",
        "installer_fetch_errors_are_domain_errors",
        "launch_requires_current_target_owned_software",
        "launch_uses_verified_private_image",
        "launch_image_regular_immutable_mode",
        "runtime_home_tmp_xdg_stay_writable_while_locked",
        "launch_denies_lifecycle_auth_plugin_marketplace_mcp_mutations",
        "launch_workspace_explicit_or_captured_cwd",
        "launch_passes_native_cwd_argument",
    ):
        if safety.get(key) is not True:
            raise ValueError(f"contract safety must set {key}=true")
    if "same user" not in str(
        safety.get("same_uid_malicious_mutation_boundary", "")
    ).replace("-", " "):
        raise ValueError("contract must document the same-user mutation boundary")
    if "sandbox off" not in str(
        safety.get("same_uid_malicious_mutation_boundary", "")
    ).replace("-", " "):
        raise ValueError("contract must document the sandbox-off same-user boundary")
    if build.get("grok_build_tested") != baseline["release"]["npm_version"]:
        raise ValueError("tested Grok Build version differs from baseline release")
    if build.get("grok_build_tested") != GROK_VERSION:
        raise ValueError("tested Grok Build version must be 0.2.112")
    if build.get("grok_build_npm_package") != NPM_PACKAGE:
        raise ValueError("npm package mismatch")
    if build.get("grok_build_npm_integrity") != NPM_INTEGRITY:
        raise ValueError("npm integrity mismatch")
    if build.get("grok_build_npm_shasum") != NPM_SHASUM:
        raise ValueError("npm shasum mismatch")
    if baseline["runtime"]["command"] != "grok":
        raise ValueError("baseline command must be grok")
    if baseline["release"].get("stable_channel_version") != GROK_VERSION:
        raise ValueError("baseline stable channel version mismatch")
    if baseline["release"].get("official_installer") != INSTALLER_URL:
        raise ValueError("baseline must pin the official vendor installer")
    if baseline["release"].get("official_installer_sha256") != INSTALLER_SHA256:
        raise ValueError("baseline installer SHA-256 mismatch")
    if baseline["release"].get("module_install_mechanism") != "vendor-installer-only":
        raise ValueError("baseline must declare vendor-installer-only install")
    if baseline["release"].get("module_npm_install_supported") is not False:
        raise ValueError("module must not support npm installation")
    if contract["plugin_marketplace"]["binary_delivery"] is not False:
        raise ValueError("builder plugin must not deliver binaries")
    runtime = contract.get("runtime_launch", {})
    if runtime.get("managed_command") != "bin/grok":
        raise ValueError("runtime launch must use target-owned bin/grok")
    if runtime.get("path_fallback") is not False:
        raise ValueError("runtime launch must disable PATH fallback")
    if runtime.get("requires_current_target_owned_software") is not True:
        raise ValueError("runtime launch must require current target-owned software")
    if runtime.get("target_role") != "managed configuration/runtime home":
        raise ValueError("runtime launch target role mismatch")
    if runtime.get("workspace_argument") != "--workspace <absolute-existing-dir>":
        raise ValueError("runtime launch workspace argument mismatch")
    if runtime.get("native_working_directory_argument") != "--cwd <workspace>":
        raise ValueError("runtime launch native cwd argument mismatch")
    if runtime.get("child_cwd") != "<workspace>":
        raise ValueError("runtime launch child cwd policy mismatch")
    if runtime.get("blocks_native_workspace_overrides") is not True:
        raise ValueError("runtime launch must block native workspace overrides")
    manifest_runtime = manifest.get("runtime_launch")
    if not isinstance(manifest_runtime, dict):
        raise ValueError("manifest runtime_launch missing")
    for key in (
        "target_role",
        "workspace_policy",
        "workspace_argument",
        "native_working_directory_argument",
        "child_cwd",
        "blocks_native_workspace_overrides",
    ):
        if manifest_runtime.get(key) != runtime.get(key):
            raise ValueError(f"manifest runtime_launch {key} mismatch")
    blocked_platform = "win" + "dows"
    if blocked_platform in json.dumps(runtime).lower():
        raise ValueError("runtime launch exposes an unsupported platform")
    lifecycle = contract.get("software_lifecycle")
    if not isinstance(lifecycle, dict) or set(lifecycle) != SOFTWARE_LIFECYCLE_KEYS:
        raise ValueError("contract software_lifecycle keys mismatch")
    if lifecycle.get("official_installer") != INSTALLER_URL:
        raise ValueError("software_lifecycle official installer mismatch")
    if lifecycle.get("installer_sha256") != INSTALLER_SHA256:
        raise ValueError("software_lifecycle installer SHA-256 mismatch")
    if lifecycle.get("installer_exact_version_arg") != GROK_VERSION:
        raise ValueError("software_lifecycle exact version argument mismatch")
    if lifecycle.get("channel") != "stable":
        raise ValueError("software_lifecycle channel mismatch")
    if lifecycle.get("npm_package") != NPM_PACKAGE:
        raise ValueError("software_lifecycle npm package mismatch")
    if lifecycle.get("npm_integrity") != NPM_INTEGRITY:
        raise ValueError("software_lifecycle npm integrity mismatch")
    if lifecycle.get("version") != GROK_VERSION:
        raise ValueError("software_lifecycle version mismatch")
    if lifecycle.get("entrypoint") != "bin/grok" or lifecycle.get("command") != "grok":
        raise ValueError("software_lifecycle must expose only grok")
    if lifecycle.get("status_executes_binary") is not False:
        raise ValueError("software-status must not execute the target binary")
    if lifecycle.get("fetch_errors_are_domain_errors") is not True:
        raise ValueError("software_lifecycle must normalize fetch errors")
    if "present=true" not in str(lifecycle.get("presence_signal", "")):
        raise ValueError("software_lifecycle must document present=true")
    stage_env = lifecycle.get("stage_env")
    if not isinstance(stage_env, dict) or stage_env.get("TMPDIR") != "<stage>/tmp":
        raise ValueError("software_lifecycle must bind installer TMPDIR to <stage>/tmp")
    if stage_env.get("GROK_CHANNEL") != "stable":
        raise ValueError("software_lifecycle must bind installer channel to stable")
    manifest_lifecycle = manifest.get("software_lifecycle")
    if not isinstance(manifest_lifecycle, dict):
        raise ValueError("manifest software_lifecycle missing")
    if manifest_lifecycle.get("installer_sha256") != INSTALLER_SHA256:
        raise ValueError("manifest installer SHA-256 mismatch")
    if manifest_lifecycle.get("version") != GROK_VERSION:
        raise ValueError("manifest software version mismatch")
    validate_manager_source()
    manager = load_manager_module()
    expected_managed = sorted([*manager.content_managed_paths(), manager.STAMP_NAME])
    if sorted(manifest.get("managed_files", [])) != expected_managed:
        raise ValueError("manifest managed_files do not match manager projection")
    for relative in (
        "builder/nddev-builder/.grok-plugin/marketplace.json",
        "builder/nddev-builder/.grok-plugin/plugin-index.json",
        "builder/nddev-builder/plugins/nddev-builder/plugin.json",
        "builder/nddev-builder/plugins/nddev-builder/skills/nddev-builder/SKILL.md",
        "builder/nddev-builder/plugins/nddev-builder/agents/nddev-builder.md",
        "cli-tools/nddev_grok_build.py",
        "CHANGELOG.md",
    ):
        if not (ROOT / relative).is_file():
            raise ValueError(f"missing required public path {relative}")
    validate_builder_toolkit(version)
    with isolated_bootstrap_root(manager):
        validate_no_replace_publication_smoke(manager)
        validate_adversarial_smokes(manager)
        validate_fetch_error_smokes(manager)
    validate_workflows()
    validate_release_workflow(manifest, contract)
    print("validate_public_contracts.py: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"validate_public_contracts.py: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
