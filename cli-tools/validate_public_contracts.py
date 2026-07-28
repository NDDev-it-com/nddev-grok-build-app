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
import urllib.error
import urllib.request
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
NPM_INTEGRITY = "sha512-dCXAiFHmn3JTOK+vPfCIzzum1GmxPB81NH73yYhqleXx1y/Ks3qjwJ+GeEXmB7eudiap98j9Nj1cDwH4lSuaOw=="
NPM_SHASUM = "cd103bfeb3d102dff87788a9cbe8d36c293112c8"
INSTALLER_URL = "https://x.ai/cli/install.sh"
INSTALLER_SHA256 = "0465d810453bbf18608ccae310fa79f4c59ae4a0538bd8a3a374ebce749be952"
METADATA_MAX_BYTES = 256 * 1024
CLEANUP_JOURNAL_MAX_BYTES = 32 * 1024 * 1024
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
    "remove_command",
    "remove_precondition",
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
PUBLIC_COMMAND_DOCS = (
    "AGENTS.md",
    "docs/SETUP_MANAGER.md",
    "builder/nddev-builder/plugins/nddev-builder/skills/nddev-builder/references/validation-workflows.md",
)
FORBIDDEN_DOCUMENTED_CACHE_COMMANDS = ("py_compile", "compileall")
EXPECTED_RUNTIME_PLATFORMS = [
    "macos-arm64",
    "macos-x64",
    "ubuntu-glibc-arm64",
    "ubuntu-glibc-x64",
]
EXPECTED_UNSUPPORTED_PLATFORMS = [
    "windows",
    "non-ubuntu-linux",
    "linux-musl",
    "unsupported-architecture",
]
EXPECTED_PLATFORM_ARCHITECTURES = {
    "macos": ["arm64", "x64"],
    "ubuntu-glibc": ["arm64", "x64"],
}
MACHINE_ARCH_BY_HOST_ARCH = {"arm64": "aarch64", "x64": "x86_64"}
EXPECTED_PLATFORM_DETECTION = {
    "canonical_host_ids": EXPECTED_RUNTIME_PLATFORMS,
    "macos_system": "Darwin",
    "ubuntu_system": "Linux",
    "ubuntu_os_release_id": "ubuntu",
    "ubuntu_libc": "glibc",
    "ubuntu_version_floor": None,
    "glibc_version_floor": None,
    "ubuntu_scope": (
        "NDDev product scope only; upstream publishes Linux assets but no Ubuntu version "
        "or glibc floor"
    ),
    "linux_distro_sources": ["/etc/os-release", "/usr/lib/os-release"],
    "standard_unsupported_categories": EXPECTED_UNSUPPORTED_PLATFORMS,
    "non_ubuntu_rejection": (
        "before target resolution, target inspection, target creation, product coordination, "
        "target anchor, installer fetch, installer staging, or launch child execution"
    ),
}
EXPECTED_VENDOR_PLATFORM_OBSERVATIONS = {
    "official_installer_assets": {
        "macos": ["grok-0.2.112-macos-x86_64", "grok-0.2.112-macos-aarch64"],
        "linux": ["grok-0.2.112-linux-x86_64", "grok-0.2.112-linux-aarch64"],
        "windows": ["grok-0.2.112-windows-x86_64.exe", "grok-0.2.112-windows-aarch64.exe"],
    },
    "installer_asset_mapping": {
        "macos-arm64": "grok-0.2.112-macos-aarch64",
        "macos-x64": "grok-0.2.112-macos-x86_64",
        "ubuntu-glibc-arm64": "grok-0.2.112-linux-aarch64",
        "ubuntu-glibc-x64": "grok-0.2.112-linux-x86_64",
    },
    "npm_package": "@xai-official/grok",
    "npm_platform_package_ids_observed_not_module_install": [
        "@xai-official/grok-darwin-x64",
        "@xai-official/grok-darwin-arm64",
        "@xai-official/grok-linux-x64",
        "@xai-official/grok-linux-arm64",
        "@xai-official/grok-win32-x64",
        "@xai-official/grok-win32-arm64",
    ],
    "product_unsupported_vendor_observations": {
        "windows": {
            "product_supported": False,
            "official_installer_assets": [
                "grok-0.2.112-windows-x86_64.exe",
                "grok-0.2.112-windows-aarch64.exe",
            ],
            "npm_optional_packages": [
                "@xai-official/grok-win32-x64",
                "@xai-official/grok-win32-arm64",
            ],
        }
    },
    "npm_package_distinction": (
        "Installer asset names are not derived from npm "
        "@xai-official/grok-{darwin,linux,win32}-{x64,arm64} package names"
    ),
    "musl_baseline_variant": None,
    "baseline_variant": None,
    "upstream_ubuntu_version_floor": None,
    "upstream_glibc_floor": None,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-archive-smoke", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--network-observation",
        action="store_true",
        help="verify explicit official source metadata over HTTPS",
    )
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
        "O_NOFOLLOW",
        "fcntl.flock",
        "LOCK_PARENT_HELD_MODE = 0o500",
        "IMMUTABLE_EXEC_MODE = 0o500",
        'LOCK_DIR_NAME = "locks"',
        "BOOTSTRAP_LOCK_NAMESPACE",
        "def bootstrap_system_root()",
        'PRODUCT_LOCK_FILE_NAME = "global.lock"',
        'TARGET_LOCK_ROOT_NAME = "target-locks"',
        "def publish_product_anchor_if_missing(",
        "def publish_target_anchor_if_missing(",
        "def recover_anchor_publication_alias(",
        "def recover_cleanup_journal_publication_alias(",
        "def write_cleanup_journal(",
        "CLEANUP_JOURNAL_NAME",
        "cleanup_pending_roots",
        "cleanup_pending_entries",
        "def acquire_product_lock(",
        "def open_external_target_lock(",
        "def acquire_bootstrap_lock(",
        "while offset < len(data)",
        "binding write made no progress",
        "os.link(temporary, path)",
        '"remove-cli"',
        '"update"',
        "def update_setup(",
        "def lexical_target_identity(",
        "def external_lifecycle_coordination(",
        "def read_lifecycle_payload(",
        "ReadLifecycleRetry",
        "READ_LIFECYCLE_MAX_ATTEMPTS",
        "def acquire_bootstrap_lock_handle_for_identity(",
        "class TreeEntry(",
        "class PreservedTree(",
        "def tree_entry_from_stat(",
        "def preserve_tree_for_rollback(",
        "def validate_backup_slot_topology(",
        "validate_backup_slot_topology(envelope_path",
        "def require_existing_file_stat_invariants(",
        "def read_existing_file(",
        "os.open(path, flags)",
        "os.fstat(descriptor)",
        "final = require_existing_managed_file(",
        "lock_parent: dict[str, TreeEntry]",
        "snapshot.lock_parent",
        "def require_command_supported_host(",
        "def remove_grok_software(",
        "def restore_lifecycle_snapshot_retry(",
        "def restore_software_snapshot_retry(",
        "preserve_file_for_rollback(",
        "ROLLBACK_MAX_ATTEMPTS",
    ):
        if marker not in source:
            raise ValueError(f"manager source is missing lock invariant marker: {marker}")
    cleanup_start = source.index("def write_cleanup_journal(")
    cleanup_end = source.index("def cleanup_root_declared_paths(")
    cleanup_source = source[cleanup_start:cleanup_end]
    for marker in ("os.replace(", "replace_file_durable("):
        if marker in cleanup_source:
            raise ValueError(f"cleanup journal publication must not use {marker}")
    if "target / root[" in source or "target / relative_root" in source:
        raise ValueError("cleanup drain must not derive deletion paths from JSON paths")
    read_start = source.index("def read_existing_file(")
    read_end = source.index("def fsync_directory(")
    read_source = source[read_start:read_end]
    if ".open(\"rb\")" in read_source or ".open('rb')" in read_source:
        raise ValueError("managed metadata reads must not reopen by pathname")
    for marker in (
        "O_NOFOLLOW",
        "require_existing_file_stat_invariants(",
        "os.open(path, flags)",
        "os.fstat(descriptor)",
        "final = require_existing_managed_file(",
        "st_mtime_ns",
    ):
        if marker not in read_source:
            raise ValueError(f"managed metadata fd reader is missing {marker}")


def validate_public_documented_commands() -> None:
    for relative in PUBLIC_COMMAND_DOCS:
        path = ROOT / relative
        text = path.read_text(encoding="utf-8")
        for marker in FORBIDDEN_DOCUMENTED_CACHE_COMMANDS:
            if marker in text:
                raise ValueError(f"{relative}: published validation command uses {marker}")
        for number, line in enumerate(text.splitlines(), start=1):
            if "python3 " not in line:
                continue
            if "python3 -B " not in line:
                raise ValueError(f"{relative}:{number}: python3 command must use -B")
            if "PYTHONDONTWRITEBYTECODE=1" not in line:
                raise ValueError(
                    f"{relative}:{number}: python3 command must set PYTHONDONTWRITEBYTECODE=1"
                )


def validate_no_python_caches(root: Path) -> None:
    for path in root.rglob("*"):
        if ".git" in path.parts:
            continue
        if path.name in {"__pycache__", ".pytest_cache", ".ruff_cache"}:
            raise ValueError(f"cache directory was created: {path.relative_to(root)}")
        if path.suffix in {".pyc", ".pyo"}:
            raise ValueError(f"bytecode cache was created: {path.relative_to(root)}")


def fetch_official_source_text(url: str) -> str:
    if not url.startswith(("https://x.ai/", "https://docs.x.ai/")):
        raise ValueError(f"network observation URL is not an official xAI source: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "nddev-grok-build-validator"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            status = getattr(response, "status", 200)
            if status < 200 or status >= 300:
                raise ValueError(f"official source returned HTTP {status}: {url}")
            content_type = response.headers.get("Content-Type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                raise ValueError(
                    f"official source has unexpected content type {content_type}: {url}"
                )
            data = response.read(1024 * 1024 + 1)
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        raise ValueError(f"official source fetch failed: {url}: {exc}") from exc
    if len(data) > 1024 * 1024:
        raise ValueError(f"official source response is too large: {url}")
    return data.decode("utf-8", errors="replace")


def validate_network_observations(contract: dict[str, Any], baseline: dict[str, Any]) -> None:
    docs_url = baseline.get("product", {}).get("official_docs_url")
    if docs_url != "https://docs.x.ai/build/overview":
        raise ValueError("baseline official_docs_url must use the live Grok Build overview")
    contract_docs = contract.get("runtime_compatibility", {}).get("official_docs", {})
    if contract_docs.get("overview") != docs_url:
        raise ValueError("contract official docs overview does not match baseline")
    source_urls = {
        item.get("url") for item in baseline.get("official_sources", []) if isinstance(item, dict)
    }
    if "https://docs.x.ai/build/getting-started" in source_urls:
        raise ValueError("baseline still references dead Grok Build getting-started docs")
    required_sources = {
        "https://x.ai/cli": ("Grok Build", "install.sh"),
        "https://docs.x.ai/build/overview": ("Grok Build", "coding agent"),
    }
    for url, markers in required_sources.items():
        if url not in source_urls and url != "https://x.ai/cli":
            raise ValueError(f"baseline official_sources missing {url}")
        text = fetch_official_source_text(url)
        for marker in markers:
            if marker not in text:
                raise ValueError(f"official source is stale or unexpected: {url}: {marker}")


def run_archive_command(archive: Path, command: list[str], env: dict[str, str]) -> None:
    completed = subprocess.run(
        command,
        cwd=archive,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    if completed.returncode != 0:
        raise ValueError(
            f"archive command failed ({' '.join(command)}): {completed.stdout}{completed.stderr}"
        )


def validate_clean_archive_cache_smoke() -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-grok-build-archive-smoke-") as raw:
        scratch = Path(raw)
        archive = scratch / "archive"
        shutil.copytree(
            ROOT,
            archive,
            ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".ruff_cache"),
        )
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "HOME": str(scratch / "home"),
            "GROK_HOME": str(scratch / "grok-home-trap"),
            "TMPDIR": str(scratch / "tmp"),
        }
        for directory in ("home", "grok-home-trap", "tmp", "targets"):
            (scratch / directory).mkdir(mode=0o700)
        manager = load_manager_module()
        status_target = scratch / "targets" / "grok-home"
        validator_command = [
            sys.executable,
            "-B",
            "cli-tools/validate_public_contracts.py",
            "--skip-archive-smoke",
        ]
        read_only_commands = [
            [sys.executable, "-B", "cli-tools/nddev_grok_build.py", "--help"],
            [sys.executable, "-B", "cli-tools/nddev_grok_build.py", "list", "--json"],
            [
                sys.executable,
                "-B",
                "cli-tools/nddev_grok_build.py",
                "status",
                "--target",
                str(status_target),
                "--json",
            ],
            [
                sys.executable,
                "-B",
                "cli-tools/nddev_grok_build.py",
                "software-status",
                "--target",
                str(status_target),
                "--json",
            ],
            [
                sys.executable,
                "-B",
                "cli-tools/nddev_grok_build.py",
                "plan",
                "--target",
                str(status_target),
                "--setup",
                "nddev-builder",
                "--profile",
                "full-auto",
                "--json",
            ],
        ]
        for command in read_only_commands:
            bootstrap_before = bootstrap_artifact_snapshot(manager)
            run_archive_command(archive, command, env)
            validate_no_python_caches(archive)
            if bootstrap_artifact_snapshot(manager) != bootstrap_before:
                raise ValueError("read-only archive command left bootstrap lock residue")
        run_archive_command(archive, validator_command, env)
        validate_no_python_caches(archive)
        validate_no_bootstrap_publication_aliases(manager)


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
        b'mkdir -p "$HOME/.config/grok-build"\n'
        b'mkdir -p "$XDG_CONFIG_HOME/grok-build"\n'
        b'mkdir -p "$XDG_CACHE_HOME/grok-build"\n'
        b'mkdir -p "$XDG_DATA_HOME/grok-build"\n'
        b'mkdir -p "$XDG_STATE_HOME/grok-build"\n'
        b'mkdir -p "$TMPDIR/grok-build"\n'
        b'mkdir -p "$GROK_HOME/runtime-state"\n'
        b'printf home > "$HOME/.config/grok-build/home.txt"\n'
        b'printf config > "$XDG_CONFIG_HOME/grok-build/config.txt"\n'
        b'printf cache > "$XDG_CACHE_HOME/grok-build/cache.txt"\n'
        b'printf data > "$XDG_DATA_HOME/grok-build/data.txt"\n'
        b'printf state > "$XDG_STATE_HOME/grok-build/session.txt"\n'
        b'printf tmp > "$TMPDIR/grok-build/tmp.txt"\n'
        b'printf target > "$GROK_HOME/runtime-state/target.txt"\n'
        b'if (printf bad > "$0") 2>/dev/null; then exit 72; fi\n'
        b'printf ok > "$GROK_HOME/runtime-state/result.txt"\n'
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
    if (
        stat.S_IMODE(manager.managed_control_dir(target).lstat().st_mode)
        != manager.OWNER_DIRECTORY_MODE
    ):
        raise ValueError("control root must stay writable after launch")
    if manager.lock_parent_dir(target).exists() or manager.lock_parent_dir(target).is_symlink():
        raise ValueError("launch created target-local lock residue")
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


def backup_entry(data: bytes) -> dict[str, Any]:
    return {
        "payload": base64.b64encode(data).decode("ascii"),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def backup_entry_payload(envelope: dict[str, Any], relative: str) -> bytes:
    entry = envelope["files"][relative]
    if not isinstance(entry, dict):
        raise ValueError(f"backup entry is not an object: {relative}")
    payload = entry["payload"]
    if not isinstance(payload, str):
        raise ValueError(f"backup entry payload is not a string: {relative}")
    return base64.b64decode(payload.encode("ascii"), validate=True)


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
        envelope["files"]["config.toml"]["payload"] = "!!!!"

    def corrupt_digest(envelope: dict[str, Any]) -> None:
        payload = backup_entry_payload(envelope, "config.toml")
        marker = manager.MANAGED_BEGIN.encode("utf-8")
        if marker not in payload:
            raise ValueError("config.toml backup is missing the managed marker")
        envelope["files"]["config.toml"] = backup_entry(
            payload.replace(marker, marker + b"\n# corrupt", 1)
        )

    def missing_path(envelope: dict[str, Any]) -> None:
        del envelope["files"]["config.toml"]

    def extra_path(envelope: dict[str, Any]) -> None:
        envelope["files"]["unmanaged.txt"] = backup_entry(b"extra")

    def wrong_scalar(envelope: dict[str, Any]) -> None:
        envelope["slot"] = str(slot)

    def extra_stamp_path(envelope: dict[str, Any]) -> None:
        stamp = json.loads(backup_entry_payload(envelope, manager.STAMP_NAME).decode("utf-8"))
        payload = b"managed by forged stamp\n"
        stamp["managed_files"]["unmanaged.txt"] = hashlib.sha256(payload).hexdigest()
        stamp_payload = (json.dumps(stamp, indent=2, sort_keys=True) + "\n").encode("utf-8")
        envelope["files"][manager.STAMP_NAME] = backup_entry(stamp_payload)
        envelope["files"]["unmanaged.txt"] = backup_entry(payload)

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


def validate_remove_cli_smokes(
    manager: Any, tmp: Path, setup: dict[str, Any], profile: dict[str, Any]
) -> None:
    target = tmp / "remove-cli-home"
    target.mkdir(mode=0o700)
    auth = target / "auth.json"
    auth.write_text('{"preserve":true}\n', encoding="utf-8")
    bin_other = target / "bin" / "keep"
    bin_other.parent.mkdir(mode=0o700)
    bin_other.write_text("keep\n", encoding="utf-8")
    other_software = target / ".nddev-software" / "other-tool" / "state.txt"
    other_software.parent.mkdir(mode=0o700, parents=True)
    other_software.write_text("keep\n", encoding="utf-8")
    manager.write_setup(target, setup, profile)
    before_setup = target_managed_bytes(manager, target)
    install_stub_software(manager, target, b"#!/bin/sh\nexit 0\n")

    removed = manager.remove_grok_software(target)
    if removed["operation"] != "remove":
        raise ValueError("remove-cli did not report remove for present software")
    if removed["removed"] != removed["changed"]:
        raise ValueError("remove-cli changed/removed path sets diverged")
    for required in (
        "bin/grok",
        manager.SOFTWARE_VERSION_BINARY_RELATIVE,
        manager.SOFTWARE_STAMP_RELATIVE,
    ):
        if required not in removed["removed"]:
            raise ValueError(f"remove-cli missing removed path: {required}")
    if manager.software_status(target)["present"]:
        raise ValueError("remove-cli left target-owned software presence")
    if target_managed_bytes(manager, target) != before_setup:
        raise ValueError("remove-cli changed setup-managed files")
    if auth.read_text(encoding="utf-8") != '{"preserve":true}\n':
        raise ValueError("remove-cli changed auth state")
    if bin_other.read_text(encoding="utf-8") != "keep\n":
        raise ValueError("remove-cli changed unrelated bin state")
    if other_software.read_text(encoding="utf-8") != "keep\n":
        raise ValueError("remove-cli changed unrelated software state")

    absent = manager.remove_grok_software(target)
    if absent["operation"] != "absent" or absent["changed"] or absent["removed"]:
        raise ValueError("remove-cli absent state is not deterministic")

    partial = tmp / "remove-cli-partial"
    partial.mkdir(mode=0o700)
    partial_grok = partial / "bin" / "grok"
    partial_grok.parent.mkdir(mode=0o700)
    partial_grok.write_bytes(b"partial\n")
    partial_grok.chmod(manager.OWNER_EXEC_MODE)
    partial_removed = manager.remove_grok_software(partial)
    if partial_removed["removed"] != ["bin/grok"]:
        raise ValueError("remove-cli partial state removed path set mismatch")
    if partial_grok.exists():
        raise ValueError("remove-cli partial state left bin/grok")


def expect_manager_main_error(manager: Any, argv: list[str], expected: str) -> None:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        rc = manager.main(argv)
    if rc != 2:
        raise ValueError(f"expected manager rc=2, got {rc}")
    payload = json.loads(output.getvalue())
    if expected not in str(payload.get("error", "")):
        raise ValueError(f"unexpected manager JSON error: {payload}")


def validate_json_argparse_errors(manager: Any) -> None:
    cases = (
        (["not-a-command", "--json"], "invalid choice"),
        (["status", "--json"], "required: --target"),
        (["restore", "--backup", "not-int", "--target", "/tmp/grok", "--json"], "invalid int"),
    )
    for argv, expected in cases:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = manager.main(list(argv))
        if rc != 2:
            raise ValueError(f"argparse JSON boundary returned {rc}: {argv}")
        if stderr.getvalue():
            raise ValueError(f"argparse JSON boundary wrote stderr: {argv}: {stderr.getvalue()}")
        lines = stdout.getvalue().splitlines()
        if len(lines) != 1:
            raise ValueError(f"argparse JSON boundary must emit one line: {argv}: {lines}")
        payload = json.loads(lines[0])
        if set(payload) != {"error"} or expected not in str(payload["error"]):
            raise ValueError(f"argparse JSON boundary emitted unexpected payload: {payload}")


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
                send_child_result(
                    write_fd, {"ok": False, "error": "operation unexpectedly succeeded"}
                )
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
        "mtime_ns": info.st_mtime_ns,
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
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        entries.append((path.relative_to(root).as_posix(), snapshot_path(path)))
    return {"root": root_snapshot, "entries": tuple(entries)}


def validate_no_bootstrap_publication_aliases(manager: Any) -> None:
    root = manager.bootstrap_product_root_path(manager.bootstrap_system_root())
    if not (root.exists() or root.is_symlink()):
        return
    pattern = re.compile(r"\..+\.[0-9]{1,20}\.[0-9]{1,20}\.tmp\Z")
    for path in root.rglob("*"):
        if pattern.fullmatch(path.name):
            raise ValueError(f"bootstrap publication alias residue remains: {path}")


@contextlib.contextmanager
def isolated_bootstrap_root(manager: Any):
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


def validate_bootstrap_handover_smoke(manager: Any, target: Path) -> None:
    identity = manager.canonical_target_identity(target.resolve(strict=True))
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
    identity = manager.canonical_target_identity(target.resolve(strict=True))
    path = manager.bootstrap_lock_path(identity)

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


def validate_anchor_recovery_smokes(manager: Any, target: Path) -> None:
    descriptor = manager.acquire_bootstrap_lock(target)
    manager.release_bootstrap_lock(descriptor)
    identity = manager.canonical_target_identity(target.resolve(strict=True))
    product_root = manager.bootstrap_product_root_path(manager.bootstrap_system_root())
    product_anchor = manager.product_anchor_path(product_root)
    target_anchor = manager.bootstrap_lock_path(identity)

    for anchor in (product_anchor, target_anchor):
        before = anchor.lstat()
        alias = anchor.with_name(f".{anchor.name}.123.456.tmp")
        os.link(anchor, alias)
        if anchor.lstat().st_nlink != 2:
            raise ValueError("anchor recovery setup did not create a hardlink alias")
        expect_manager_error(manager, lambda: manager.status_payload(target), "hardlink count")
        unchanged = anchor.lstat()
        if not (alias.exists() or alias.is_symlink()):
            raise ValueError("read-only anchor validation removed a publication alias")
        if unchanged.st_nlink != 2:
            raise ValueError("read-only anchor validation changed the hardlink count")
        if (unchanged.st_dev, unchanged.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("read-only anchor validation changed the final anchor inode")
        manager.release_bootstrap_lock(manager.acquire_bootstrap_lock(target))
        after = anchor.lstat()
        if alias.exists() or alias.is_symlink():
            raise ValueError("mutating anchor recovery did not remove the publication alias")
        if after.st_nlink != 1:
            raise ValueError("anchor recovery did not restore nlink==1")
        if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("anchor recovery changed the final anchor inode")

    unknown = target_anchor.with_name(f"{target_anchor.name}.unknown-hardlink")
    os.link(target_anchor, unknown)
    try:
        expect_manager_error(
            manager,
            lambda: manager.release_bootstrap_lock(manager.acquire_bootstrap_lock(target)),
            "recoverable publication alias",
        )
    finally:
        with contextlib.suppress(FileNotFoundError):
            unknown.unlink()
    validate_no_bootstrap_publication_aliases(manager)


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


def validate_platform_scope(
    manager: Any,
    manifest: dict[str, Any],
    contract: dict[str, Any],
    baseline: dict[str, Any],
) -> None:
    manifest_runtime = manifest.get("runtime_launch")
    contract_runtime = contract.get("runtime_launch")
    if not isinstance(manifest_runtime, dict) or not isinstance(contract_runtime, dict):
        raise ValueError("runtime_launch metadata missing")
    for label, runtime in (("manifest", manifest_runtime), ("contract", contract_runtime)):
        if runtime.get("supported_platforms") != EXPECTED_RUNTIME_PLATFORMS:
            raise ValueError(f"{label} runtime_launch supported_platforms host IDs mismatch")
        if runtime.get("unsupported_platforms") != EXPECTED_UNSUPPORTED_PLATFORMS:
            raise ValueError(f"{label} runtime_launch unsupported_platforms mismatch")
        if runtime.get("supported_architectures") != EXPECTED_PLATFORM_ARCHITECTURES:
            raise ValueError(f"{label} runtime_launch supported_architectures mismatch")
        if runtime.get("platform_detection") != EXPECTED_PLATFORM_DETECTION:
            raise ValueError(f"{label} runtime_launch platform_detection mismatch")
        if runtime.get("vendor_platform_observations") != EXPECTED_VENDOR_PLATFORM_OBSERVATIONS:
            raise ValueError(f"{label} runtime_launch vendor_platform_observations mismatch")

    support = baseline.get("platform_support")
    if not isinstance(support, dict):
        raise ValueError("baseline platform_support missing")
    supported = support.get("nddev_supported_hosts")
    if not isinstance(supported, list) or len(supported) != len(EXPECTED_RUNTIME_PLATFORMS):
        raise ValueError("baseline supported host list mismatch")
    by_host = {item.get("host_id"): item for item in supported if isinstance(item, dict)}
    if set(by_host) != set(EXPECTED_RUNTIME_PLATFORMS):
        raise ValueError("baseline supported hosts must use canonical NDDev host IDs")
    for host_id, expected_asset in EXPECTED_VENDOR_PLATFORM_OBSERVATIONS[
        "installer_asset_mapping"
    ].items():
        host = by_host[host_id]
        if host.get("vendor_installer_asset") != expected_asset:
            raise ValueError(f"baseline host vendor asset mismatch: {host_id}")
        if host_id.startswith("ubuntu-glibc-"):
            if host.get("os_release_id") != "ubuntu" or host.get("libc") != "glibc":
                raise ValueError("baseline Ubuntu hosts must bind ID=ubuntu and glibc")
            if host.get("variants") != ["desktop", "server"]:
                raise ValueError("baseline Ubuntu hosts must cover desktop and server")
        elif host.get("variants") != ["desktop"]:
            raise ValueError("baseline macOS hosts must be desktop-scoped")
    if support.get("standard_unsupported_categories") != EXPECTED_UNSUPPORTED_PLATFORMS:
        raise ValueError("baseline unsupported categories mismatch")
    if "no Ubuntu version or glibc floor" not in str(support.get("ubuntu_scope", "")):
        raise ValueError("baseline must label Ubuntu as NDDev product scope only")
    if support.get("ubuntu_os_release_id") != "ubuntu" or support.get("ubuntu_libc") != "glibc":
        raise ValueError("baseline Ubuntu host check mismatch")
    if support.get("upstream_ubuntu_version_floor") is not None:
        raise ValueError("baseline must not invent an Ubuntu version floor")
    if support.get("upstream_glibc_floor") is not None:
        raise ValueError("baseline must not invent a glibc floor")
    if (
        support.get("official_installer_assets")
        != EXPECTED_VENDOR_PLATFORM_OBSERVATIONS["official_installer_assets"]
    ):
        raise ValueError("baseline official installer asset names mismatch")
    if (
        support.get("installer_asset_mapping")
        != EXPECTED_VENDOR_PLATFORM_OBSERVATIONS["installer_asset_mapping"]
    ):
        raise ValueError("baseline installer asset mapping mismatch")
    if (
        support.get("npm_platform_package_ids_observed_not_module_install")
        != EXPECTED_VENDOR_PLATFORM_OBSERVATIONS[
            "npm_platform_package_ids_observed_not_module_install"
        ]
    ):
        raise ValueError("baseline npm platform package observation mismatch")
    unsupported_vendor = support.get("product_unsupported_vendor_observations")
    if (
        unsupported_vendor
        != EXPECTED_VENDOR_PLATFORM_OBSERVATIONS["product_unsupported_vendor_observations"]
    ):
        raise ValueError("baseline product-unsupported vendor observations mismatch")
    if "@xai-official/grok-{darwin,linux,win32}-{x64,arm64}" not in str(
        support.get("npm_package_distinction", "")
    ):
        raise ValueError("baseline must distinguish installer assets from npm platform packages")
    if support.get("musl_baseline_variant") is not None:
        raise ValueError("baseline must not invent a musl variant")
    if support.get("baseline_variant") is not None:
        raise ValueError("baseline must not invent a baseline variant")
    upstream = support.get("upstream_linux_install_metadata_preserved")
    if not isinstance(upstream, dict):
        raise ValueError("baseline upstream Linux install metadata missing")
    release = baseline["release"]
    for key, release_key in (
        ("official_installer", "official_installer"),
        ("official_installer_sha256", "official_installer_sha256"),
        ("npm_package", "npm_package"),
        ("npm_tarball", "npm_tarball"),
        ("npm_integrity", "npm_integrity"),
        ("npm_shasum", "npm_shasum"),
    ):
        if upstream.get(key) != release.get(release_key):
            raise ValueError(f"baseline upstream Linux metadata mismatch: {key}")

    for platform_id, system, os_release, libc_info, prefix in (
        ("macos", "Darwin", {}, None, "macos"),
        ("ubuntu", "Linux", {"ID": "ubuntu", "ID_LIKE": "debian"}, ("glibc", ""), "ubuntu-glibc"),
    ):
        for host_architecture in EXPECTED_PLATFORM_ARCHITECTURES[prefix]:
            architecture = MACHINE_ARCH_BY_HOST_ARCH[host_architecture]
            info = manager.runtime_platform_info(
                system_name=system,
                machine_name=architecture,
                os_release=os_release,
                libc_info=libc_info,
            )
            if not info.supported or info.platform_id != platform_id:
                raise ValueError(f"{platform_id}/{architecture} platform model was rejected")
            if info.host_id != f"{prefix}-{host_architecture}":
                raise ValueError(f"{platform_id}/{architecture} host ID mismatch: {info.host_id}")
            if (
                info.vendor_installer_asset
                != EXPECTED_VENDOR_PLATFORM_OBSERVATIONS["installer_asset_mapping"][info.host_id]
            ):
                raise ValueError(f"{info.host_id} vendor installer asset mismatch")
            if manager.require_supported_runtime_platform(info) != info:
                raise ValueError("runtime platform preflight did not return the checked model")

    for os_release in ({"ID": "debian", "ID_LIKE": "ubuntu"}, {"ID": "fedora"}, {}):
        info = manager.runtime_platform_info(
            system_name="Linux",
            machine_name="x86_64",
            os_release=os_release,
            libc_info=("glibc", ""),
        )
        if info.supported or info.platform_id != "non-ubuntu-linux":
            raise ValueError("non-Ubuntu Linux platform model was accepted")
        expect_manager_error(
            manager,
            lambda checked=info: manager.require_supported_runtime_platform(checked),
            "Ubuntu is required",
        )
    musl_info = manager.runtime_platform_info(
        system_name="Linux",
        machine_name="x86_64",
        os_release={"ID": "ubuntu"},
        libc_info=("musl", "1.2.5"),
    )
    if musl_info.supported or musl_info.platform_id != "linux-musl":
        raise ValueError("Linux musl platform model was accepted")
    expect_manager_error(
        manager,
        lambda checked=musl_info: manager.require_supported_runtime_platform(checked),
        "Ubuntu glibc is required",
    )
    arch_info = manager.runtime_platform_info(
        system_name="Darwin",
        machine_name="ppc64",
    )
    if arch_info.supported or arch_info.platform_id != "unsupported-architecture":
        raise ValueError("unsupported architecture platform model was accepted")
    windows_info = manager.runtime_platform_info(system_name="Windows", machine_name="x86_64")
    if windows_info.supported or windows_info.platform_id != "windows":
        raise ValueError("Windows platform model was accepted")
    if windows_info.vendor_installer_asset != "grok-0.2.112-windows-x86_64.exe":
        raise ValueError("Windows x64 vendor observation mismatch")
    windows_arm = manager.runtime_platform_info(system_name="Windows", machine_name="aarch64")
    if windows_arm.supported or windows_arm.platform_id != "windows":
        raise ValueError("Windows arm64 platform model was accepted")
    if windows_arm.vendor_installer_asset != "grok-0.2.112-windows-aarch64.exe":
        raise ValueError("Windows arm64 vendor observation mismatch")

    original_info = manager.runtime_platform_info
    original_read = manager.read_pinned_installer
    original_stage = manager.run_vendor_installer
    original_popen = manager.subprocess.Popen
    original_product_lock = manager.acquire_product_lock
    original_bootstrap = manager.acquire_bootstrap_lock
    original_bootstrap_handle = manager.acquire_bootstrap_lock_handle_for_identity
    original_validate_target = manager.validate_target
    touched = {
        "target": False,
        "bootstrap": False,
        "fetch": False,
        "stage": False,
        "launch": False,
    }

    def non_ubuntu_info() -> Any:
        return original_info(
            system_name="Linux",
            machine_name="x86_64",
            os_release={"ID": "debian", "ID_LIKE": "ubuntu"},
            libc_info=("glibc", ""),
        )

    def fail_fetch() -> Any:
        touched["fetch"] = True
        raise ValueError("network fetch should not be reached")

    def fail_stage(*_args: Any, **_kwargs: Any) -> Any:
        touched["stage"] = True
        raise ValueError("installer staging should not be reached")

    class FailLaunch:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            touched["launch"] = True
            raise ValueError("launch child should not be reached")

    def fail_bootstrap(*_args: Any, **_kwargs: Any) -> Any:
        touched["bootstrap"] = True
        raise ValueError("bootstrap lock should not be reached")

    def fail_target(*_args: Any, **_kwargs: Any) -> Any:
        touched["target"] = True
        raise ValueError("target resolution should not be reached")

    try:
        manager.runtime_platform_info = non_ubuntu_info
        manager.read_pinned_installer = fail_fetch
        manager.run_vendor_installer = fail_stage
        manager.subprocess.Popen = FailLaunch
        manager.acquire_product_lock = fail_bootstrap
        manager.acquire_bootstrap_lock = fail_bootstrap
        manager.acquire_bootstrap_lock_handle_for_identity = fail_bootstrap
        manager.validate_target = fail_target
        with tempfile.TemporaryDirectory(prefix="nddev-grok-build-platform-") as raw:
            target = Path(raw) / "target"
            setup = manager.load_setup(manager.DEFAULT_SETUP_ID)
            profile = manager.load_profile(manager.DEFAULT_PROFILE_ID)
            operations = (
                lambda: manager.status_payload(target),
                lambda: manager.software_status(target),
                lambda: manager.plan_payload(target, setup, profile),
                lambda: manager.write_setup(target, setup, profile),
                lambda: manager.update_setup(target),
                lambda: manager.write_setup(target, setup, profile, require_existing=True),
                lambda: manager.migrate_setup(target, setup, None),
                lambda: manager.restore_backup(target, 0),
                lambda: manager.remove_setup(target),
                lambda: manager.install_grok_software(target, "install-cli"),
                lambda: manager.install_grok_software(target, "update-cli"),
                lambda: manager.remove_grok_software(target),
                lambda: manager.launch(target, []),
            )
            for operation in operations:
                expect_manager_error(manager, operation, "Ubuntu is required")
                if target.exists():
                    raise ValueError("unsupported host preflight created target state")
        if any(touched.values()):
            raise ValueError(f"non-Ubuntu preflight reached runtime side effects: {touched}")
    finally:
        manager.runtime_platform_info = original_info
        manager.read_pinned_installer = original_read
        manager.run_vendor_installer = original_stage
        manager.subprocess.Popen = original_popen
        manager.acquire_product_lock = original_product_lock
        manager.acquire_bootstrap_lock = original_bootstrap
        manager.acquire_bootstrap_lock_handle_for_identity = original_bootstrap_handle
        manager.validate_target = original_validate_target


def validate_lifecycle_ordering_smoke(manager: Any) -> None:
    setup = manager.load_setup(manager.DEFAULT_SETUP_ID)
    profile = manager.load_profile(manager.DEFAULT_PROFILE_ID)
    order: list[str] = []
    product_depth = {"value": 0}
    target_depth = {"value": 0}
    original_acquire_product = manager.acquire_product_lock
    original_release_product = manager.release_product_lock
    original_open_target_lock = manager.open_external_target_lock
    original_release_target_lock = manager.release_external_target_lock
    original_validate_target = manager.validate_target
    original_require_parent = manager.require_safe_target_parent
    original_missing_chain = manager.missing_directory_chain
    original_status_locked = manager.status_payload_locked
    original_software_locked = manager.software_status_locked
    original_lifecycle_snapshot = manager.snapshot_lifecycle_state
    original_software_snapshot = manager.snapshot_software_state
    original_read_stamp = manager.read_stamp
    original_read_installer = manager.read_pinned_installer
    original_stage = manager.run_vendor_installer
    original_popen = manager.subprocess.Popen

    def external_depth() -> int:
        return product_depth["value"] + target_depth["value"]

    def require_external(label: str) -> None:
        if external_depth() <= 0:
            raise ValueError(f"{label} ran before external lifecycle lock")
        order.append(label)

    def traced_acquire_product(*, create: bool, exclusive: bool) -> Any:
        order.append(f"product-enter:create={create}:exclusive={exclusive}")
        handle = original_acquire_product(create=create, exclusive=exclusive)
        if handle is not None:
            product_depth["value"] += 1
            order.append(f"product-held:{handle.path.name}")
        return handle

    def traced_release_product(handle: Any) -> None:
        if handle is not None:
            original_release_product(handle)
            product_depth["value"] -= 1
            order.append(f"product-release:{handle.path.name}")

    def traced_open_target_lock(
        product_root: Path,
        identity: str,
        *,
        exclusive: bool,
        create: bool,
        blocking: bool = False,
    ) -> Any:
        require_external("open_external_target_lock")
        handle = original_open_target_lock(
            product_root,
            identity,
            exclusive=exclusive,
            create=create,
            blocking=blocking,
        )
        if handle is not None:
            target_depth["value"] += 1
            order.append(f"target-held:{handle.path.name}")
        return handle

    def traced_release_target_lock(handle: Any) -> None:
        if handle is not None:
            original_release_target_lock(handle)
            target_depth["value"] -= 1
            order.append(f"target-release:{handle.path.name}")

    def traced_validate(target: Path, *, create: bool = False) -> Path:
        require_external("validate_target")
        return original_validate_target(target, create=create)

    def traced_parent(path: Path, label: str) -> Any:
        require_external(f"require_safe_target_parent:{label}")
        return original_require_parent(path, label)

    def traced_missing(path: Path) -> list[Path]:
        require_external("missing_directory_chain")
        return original_missing_chain(path)

    def traced_status(target: Path) -> dict[str, Any]:
        require_external("status_payload_locked")
        return original_status_locked(target)

    def traced_software(target: Path) -> dict[str, Any]:
        require_external("software_status_locked")
        return original_software_locked(target)

    def traced_lifecycle_snapshot(*args: Any, **kwargs: Any) -> Any:
        require_external("snapshot_lifecycle_state")
        return original_lifecycle_snapshot(*args, **kwargs)

    def traced_software_snapshot(*args: Any, **kwargs: Any) -> Any:
        require_external("snapshot_software_state")
        return original_software_snapshot(*args, **kwargs)

    def traced_read_stamp(*args: Any, **kwargs: Any) -> Any:
        require_external("read_stamp")
        return original_read_stamp(*args, **kwargs)

    def traced_read_installer() -> Any:
        require_external("read_pinned_installer")
        raise manager.GrokBuildSetupError("injected installer read stop")

    def traced_stage(*_args: Any, **_kwargs: Any) -> Any:
        require_external("run_vendor_installer")
        raise manager.GrokBuildSetupError("installer stage should not be reached")

    class FailLaunch:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            require_external("launch child")
            raise manager.GrokBuildSetupError("launch child should not be reached")

    def exact_bootstrap_tree(root: Path) -> tuple[tuple[str, dict[str, Any]], ...]:
        if not root.exists() and not root.is_symlink():
            return ((".", {"exists": False}),)
        paths = [root]
        if root.is_dir() and not root.is_symlink():
            paths.extend(sorted(root.rglob("*")))
        entries: list[tuple[str, dict[str, Any]]] = []
        for path in paths:
            info = path.lstat()
            relative = "." if path == root else path.relative_to(root).as_posix()
            item = {
                "mode": stat.S_IMODE(info.st_mode),
                "type": "dir"
                if stat.S_ISDIR(info.st_mode)
                else "file"
                if stat.S_ISREG(info.st_mode)
                else "symlink"
                if stat.S_ISLNK(info.st_mode)
                else "other",
                "ino": int(info.st_ino),
                "mtime_ns": int(info.st_mtime_ns),
            }
            if stat.S_ISREG(info.st_mode):
                data = path.read_bytes()
                item["sha256"] = hashlib.sha256(data).hexdigest()
            entries.append((relative, item))
        return tuple(entries)

    try:
        manager.acquire_product_lock = traced_acquire_product
        manager.release_product_lock = traced_release_product
        manager.open_external_target_lock = traced_open_target_lock
        manager.release_external_target_lock = traced_release_target_lock
        manager.validate_target = traced_validate
        manager.require_safe_target_parent = traced_parent
        manager.missing_directory_chain = traced_missing
        manager.status_payload_locked = traced_status
        manager.software_status_locked = traced_software
        manager.snapshot_lifecycle_state = traced_lifecycle_snapshot
        manager.snapshot_software_state = traced_software_snapshot
        manager.read_stamp = traced_read_stamp
        manager.read_pinned_installer = traced_read_installer
        manager.run_vendor_installer = traced_stage
        manager.subprocess.Popen = FailLaunch
        with tempfile.TemporaryDirectory(prefix="nddev-grok-build-order-") as raw:
            tmp = Path(raw)
            target = tmp / "target"
            seed = manager.acquire_product_lock(create=True, exclusive=True)
            manager.release_product_lock(seed)
            for operation in (
                lambda: manager.status_payload(target),
                lambda: manager.software_status(target),
                lambda: manager.plan_payload(target, setup, profile),
                lambda: manager.remove_setup(target),
                lambda: manager.remove_grok_software(target),
                lambda: manager.launch(target, []),
                lambda: manager.write_setup(tmp / "setup-install", setup, profile),
                lambda: manager.write_setup(
                    tmp / "setup-switch",
                    setup,
                    profile,
                    require_existing=True,
                ),
                lambda: manager.update_setup(tmp / "setup-update"),
                lambda: manager.migrate_setup(tmp / "setup-migrate", setup, None),
                lambda: manager.restore_backup(tmp / "setup-restore", 0),
            ):
                with contextlib.suppress(manager.GrokBuildSetupError):
                    operation()
            failure_target = tmp / "failure-target"
            bootstrap_before_failure = exact_bootstrap_tree(manager.bootstrap_system_root())
            expect_manager_error(
                manager,
                lambda: manager.install_grok_software(failure_target, "install-cli"),
                "injected installer read stop",
            )
            if failure_target.exists() or failure_target.is_symlink():
                raise ValueError("failed install-cli ordering smoke left target state")
            after_failure = exact_bootstrap_tree(manager.bootstrap_system_root())
            if after_failure == bootstrap_before_failure:
                raise ValueError("failed install-cli did not publish monotonic target coordination")
            validate_no_bootstrap_publication_aliases(manager)
    finally:
        manager.acquire_product_lock = original_acquire_product
        manager.release_product_lock = original_release_product
        manager.open_external_target_lock = original_open_target_lock
        manager.release_external_target_lock = original_release_target_lock
        manager.validate_target = original_validate_target
        manager.require_safe_target_parent = original_require_parent
        manager.missing_directory_chain = original_missing_chain
        manager.status_payload_locked = original_status_locked
        manager.software_status_locked = original_software_locked
        manager.snapshot_lifecycle_state = original_lifecycle_snapshot
        manager.snapshot_software_state = original_software_snapshot
        manager.read_stamp = original_read_stamp
        manager.read_pinned_installer = original_read_installer
        manager.run_vendor_installer = original_stage
        manager.subprocess.Popen = original_popen
    if not order or not any(item.startswith("product-held:") for item in order):
        raise ValueError("lifecycle ordering smoke did not exercise external lock")
    if not any(item.startswith("target-held:") for item in order):
        raise ValueError("lifecycle ordering smoke did not exercise target lock handoff")


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
        setup_update = manager.update_setup(target)
        if setup_update["operation"] != "current" or setup_update["changed"]:
            raise ValueError("setup update must be a warm no-op when installed content is current")
        if not sibling_lock.is_dir() or not sibling_backups.is_dir():
            raise ValueError("manager touched precreated sibling lock/backup state")
        status = manager.status_payload(target)
        if status["launchable"] or status.get("software_current") is not False:
            raise ValueError("status launchable must be false without current software")

        validate_bootstrap_handover_smoke(manager, target)
        validate_bootstrap_binding_smokes(manager, target)
        validate_anchor_recovery_smokes(manager, target)
        validate_restore_backup_smokes(manager, target, setup)
        validate_remove_cli_smokes(manager, tmp, setup, profile)

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

        original = b"#!/bin/sh\nprintf 'original\\n' > \"$GROK_HOME/stable-fd-result.txt\"\n"
        replacement = b"#!/bin/sh\nprintf 'replacement\\n' > \"$GROK_HOME/stable-fd-result.txt\"\n"
        validate_runtime_write_smoke(manager, target)
        original_digest = install_stub_software(manager, target, original)
        original_popen = manager.subprocess.Popen

        class FakePopen:
            def __init__(self, command: list[str], **kwargs: Any) -> None:
                control = manager.managed_control_dir(target)
                control_mode = stat.S_IMODE(control.lstat().st_mode)
                if control_mode != manager.OWNER_DIRECTORY_MODE:
                    raise ValueError("launch made the control root non-writable")
                if (
                    manager.lock_parent_dir(target).exists()
                    or manager.lock_parent_dir(target).is_symlink()
                ):
                    raise ValueError("launch created target-local lock residue")
                fork_expect_manager_error(
                    manager,
                    lambda: manager.remove_setup(target),
                    "target is locked",
                )
                safe_profile = manager.load_profile("safe")
                fork_expect_manager_error(
                    manager,
                    lambda: manager.write_setup(target, setup, safe_profile, require_existing=True),
                    "target is locked",
                )
                fork_expect_manager_error(
                    manager,
                    lambda: manager.write_setup(target, setup, profile),
                    "target is locked",
                )
                launch_image = Path(command[0])
                if launch_image.parent.resolve() != manager.launch_image_dir(target).resolve():
                    raise ValueError("launch did not use a private target-internal launch image")
                if (
                    stat.S_IMODE(launch_image.parent.lstat().st_mode)
                    != manager.LOCK_PARENT_HELD_MODE
                ):
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
                return self.returncode

            def kill(self) -> None:
                self.returncode = -9

        try:
            manager.subprocess.Popen = FakePopen
            if manager.launch(target, ["doctor"]) != 0:
                raise ValueError("stubbed launch did not return success")
        finally:
            manager.subprocess.Popen = original_popen
        if manager.lock_parent_dir(target).exists() or manager.lock_parent_dir(target).is_symlink():
            raise ValueError("launch left target-local lock residue")
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
            raise ValueError(
                f"builder payload must not ship executable files: {path.relative_to(ROOT)}"
            )
        if path.suffix.lower() in {".bin", ".exe", ".dmg", ".pkg", ".deb", ".rpm", ".zip", ".tgz"}:
            raise ValueError(
                f"builder payload must not ship binary/runtime archives: {path.relative_to(ROOT)}"
            )

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
        raise ValueError(
            f"release runtime_paths missing runtime closure: {sorted(missing_runtime)}"
        )
    validate_claude_bridge(archive_paths, runtime_paths)


def validate_skill_local_references(plugin_root: Path, skill_path: Path, text: str) -> None:
    plugin_real = plugin_root.resolve()
    for reference in re.findall(r"`([^`]+)`", text):
        if not reference.endswith(".md"):
            continue
        if not (reference.startswith("../") or reference.startswith("references/")):
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
    args = parse_args(argv)
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
    if build.get("python_requires") != ">=3.9":
        raise ValueError("build/version.json python_requires must be >=3.9")
    if contract.get("version_ref") != "build/version.json":
        raise ValueError("contract version_ref must point at build/version.json")
    if contract.get("manifest_ref") != "build/manifest.json":
        raise ValueError("contract manifest_ref must point at build/manifest.json")
    if "skeleton" in contract:
        raise ValueError("contract must not expose skeleton status")
    if manifest.get("setup_ids") != ids or contract["setup_system"]["setup_ids"] != ids:
        raise ValueError("setup ids are not synchronized")
    if (
        manifest.get("profile_ids") != profiles
        or contract["setup_system"]["profile_ids"] != profiles
    ):
        raise ValueError("profile ids are not synchronized")
    if (
        manifest.get("default_setup") != "nddev-builder"
        or manifest.get("default_profile") != "full-auto"
    ):
        raise ValueError("manifest default setup/profile mismatch")
    command_policy = manifest.get("command_policy")
    if not isinstance(command_policy, dict):
        raise ValueError("manifest command_policy missing")
    for key in ("json_supported", "target_required"):
        values = command_policy.get(key)
        if not isinstance(values, list) or "update" not in values:
            raise ValueError(f"manifest command_policy.{key} must include setup update")
    setup_system = contract.get("setup_system")
    if not isinstance(setup_system, dict):
        raise ValueError("contract setup_system missing")
    if " update " not in f" {setup_system.get('update_command', '')} ":
        raise ValueError("contract setup_system must expose setup update_command")
    if "update-cli" in str(setup_system.get("update_command", "")):
        raise ValueError("setup update_command must be distinct from update-cli")
    backup_policy = manifest.get("backup_policy")
    if not isinstance(backup_policy, dict):
        raise ValueError("manifest backup_policy missing")
    if backup_policy.get("location") != "$GROK_HOME/.nddev-grok-build/backups":
        raise ValueError("manifest backup policy must be target-internal")
    for key in (
        "strict_envelope_validation",
        "base64_validate",
        "entry_payload_size_sha256_validated",
        "restored_stamp_path_set_validated",
        "transactional_slot_replacement",
        "failed_mutation_removes_new_backup",
    ):
        if backup_policy.get(key) is not True:
            raise ValueError(f"manifest backup_policy must set {key}=true")
    transaction = manifest.get("transaction_policy")
    if not isinstance(transaction, dict):
        raise ValueError("manifest transaction_policy missing")
    if transaction.get("existing_target_mode_required") != "0700":
        raise ValueError("manifest must require existing target mode 0700")
    lock_surface = str(transaction.get("external_bootstrap_lock", ""))
    if "global.lock" not in lock_surface or "target-locks/<sha256" not in lock_surface:
        raise ValueError(
            "manifest external bootstrap lock path must name product and target anchors"
        )
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
    if transaction.get("external_bootstrap_product_anchor") != "global.lock":
        raise ValueError("manifest external product anchor mismatch")
    if transaction.get("external_bootstrap_target_anchor_root") != "target-locks":
        raise ValueError("manifest external target anchor root mismatch")
    if transaction.get("external_bootstrap_target_anchor_suffix") != ".lock":
        raise ValueError("manifest external target anchor suffix mismatch")
    if "JSON" not in str(transaction.get("external_bootstrap_lock_binding", "")):
        raise ValueError("manifest external bootstrap lock binding missing")
    identity_description = str(transaction.get("external_bootstrap_lock_target_identity", ""))
    if "canonical target" not in identity_description:
        raise ValueError("manifest canonical target handoff ordering mismatch")
    if "cold read-only no-anchor" not in identity_description:
        raise ValueError("manifest cold read-only exception mismatch")
    if transaction.get("external_bootstrap_lock_from_ambient_tmpdir") is not False:
        raise ValueError("manifest external bootstrap lock must ignore ambient TMPDIR")
    if transaction.get("external_bootstrap_lock_child_env") is not False:
        raise ValueError("manifest external bootstrap lock must not be exposed to child env")
    if transaction.get("external_lock_acquired_before_target_inspection") is not True:
        raise ValueError("manifest external lock must be acquired before target inspection")
    if "lock" in transaction or "lock_parent" in transaction:
        raise ValueError("manifest must not publish a target-local lock path")
    if "external regular files with fcntl.flock" not in str(transaction.get("lock_type", "")):
        raise ValueError("manifest lock_type mismatch")
    if transaction.get("lock_file_mode") != "0600":
        raise ValueError("manifest lock file mode mismatch")
    if transaction.get("control_root_mode_while_locked") != "0700":
        raise ValueError("manifest must keep the control root writable while locked")
    if transaction.get("target_local_lock_created") is not False:
        raise ValueError("manifest must declare no target-local lock creation")
    if transaction.get("target_anchor_lock_held_through_launch_child") is not True:
        raise ValueError(
            "manifest must require launch to hold the target anchor through child exit"
        )
    if transaction.get("lock_crash_recovery") is not True:
        raise ValueError("manifest must declare lock crash recovery")
    if transaction.get("lock_order") != (
        "product anchor lock first, canonical target anchor handoff second; "
        "different targets run concurrently after product handoff"
    ):
        raise ValueError("manifest lock ordering mismatch")
    if "hard-link no-replace" not in str(transaction.get("external_anchor_publication", "")):
        raise ValueError("manifest must declare hard-link no-replace publication")
    if transaction.get("external_anchor_commit_point") != "final-path publication":
        raise ValueError("manifest anchor commit point mismatch")
    if transaction.get("external_anchor_hardlink_alias_recovery") is not True:
        raise ValueError("manifest must declare hardlink alias recovery")
    if transaction.get("external_anchor_final_unlinked_on_recovery") is not False:
        raise ValueError("manifest must never unlink final anchors during recovery")
    if transaction.get("cleanup_journal_immutable_pending") is not True:
        raise ValueError("manifest must declare immutable pending cleanup journal")
    if transaction.get("cleanup_journal_top_level_pending") is not True:
        raise ValueError("manifest must declare top-level cleanup_pending")
    if "hard-link no-replace" not in str(transaction.get("cleanup_journal_publication", "")):
        raise ValueError("manifest must declare cleanup journal hard-link no-replace publication")
    if transaction.get("cleanup_journal_commit_point") != "final-path publication":
        raise ValueError("manifest cleanup journal commit point mismatch")
    if transaction.get("cleanup_journal_hardlink_alias_recovery") != (
        "mutation-only under exclusive target coordination"
    ):
        raise ValueError("manifest cleanup journal alias recovery scope mismatch")
    if transaction.get("cleanup_journal_read_only_recovery") is not False:
        raise ValueError("manifest read-only cleanup journal recovery must be false")
    if transaction.get("cleanup_journal_serialized_max_bytes") != CLEANUP_JOURNAL_MAX_BYTES:
        raise ValueError("manifest cleanup journal serialized byte bound mismatch")
    if transaction.get("cleanup_journal_fixed_parent") != "$GROK_HOME/.nddev-grok-build/tmp":
        raise ValueError("manifest cleanup journal fixed parent mismatch")
    if transaction.get("cleanup_journal_path") != (
        "$GROK_HOME/.nddev-grok-build/cleanup/NDDEV-GROK-BUILD-CLEANUP.json"
    ):
        raise ValueError("manifest cleanup journal path mismatch")
    if transaction.get("cleanup_pending_status_metadata") != [
        "cleanup_pending",
        "cleanup_pending_roots",
        "cleanup_pending_entries",
    ]:
        raise ValueError("manifest cleanup pending metadata mismatch")
    if "lifecycle work" not in str(transaction.get("cleanup_pending_noop_exception", "")):
        raise ValueError("manifest cleanup pending no-op exception mismatch")
    if transaction.get("external_read_only_cold_no_anchor_creates_lock") is not False:
        raise ValueError("manifest cold read-only path must create no anchors")
    if transaction.get("external_read_only_cold_no_anchor_post_observation_retry") is not True:
        raise ValueError("manifest cold read-only path must retry after anchor publication")
    if transaction.get("external_read_only_seeded_uses_product_coordination") is not True:
        raise ValueError("manifest seeded read-only path must use product coordination")
    if transaction.get("same_canonical_target_serialized") is not True:
        raise ValueError("manifest must serialize same canonical targets")
    if transaction.get("different_canonical_targets_concurrent_after_handoff") is not True:
        raise ValueError("manifest must allow different targets after product handoff")
    if transaction.get("launch_requires_current_software") is not True:
        raise ValueError("manifest must require current software for launch")
    if transaction.get("atomic_write_order") != (
        "temporary write, temporary mode, file fsync, replace, parent fsync"
    ):
        raise ValueError("manifest atomic write order mismatch")
    for key in (
        "post_replace_failure_rolls_back",
        "object_preserving_rollback",
        "same_setup_profile_noop",
        "postconditions_compare_intended_bytes",
        "software_no_target_stage_or_rollback_dirs",
        "supported_host_preflight_before_target_resolution",
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
    if "same user" not in str(transaction.get("same_uid_malicious_mutation_boundary", "")).replace(
        "-", " "
    ):
        raise ValueError("manifest must document the same-user mutation boundary")
    if "sandbox off" not in str(
        transaction.get("same_uid_malicious_mutation_boundary", "")
    ).replace("-", " "):
        raise ValueError("manifest must document the sandbox-off same-user boundary")
    functionality = contract.get("safety")
    if not isinstance(functionality, dict):
        raise ValueError("contract safety missing")
    for key in (
        "cleanup_journal_immutable_pending",
        "cleanup_journal_top_level_pending",
        "cleanup_journal_mutation_only_recovery",
        "cleanup_pending_status_plan_software_status_metadata",
        "cleanup_pending_drain_is_lifecycle_work",
    ):
        if functionality.get(key) is not True:
            raise ValueError(f"contract safety must set {key}=true")
    if functionality.get("cleanup_journal_read_only_recovery") is not False:
        raise ValueError("contract safety must disable read-only cleanup journal recovery")
    if functionality.get("cleanup_journal_serialized_max_bytes") != CLEANUP_JOURNAL_MAX_BYTES:
        raise ValueError("contract safety cleanup journal serialized byte bound mismatch")
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
        "external_anchor_final_path_commit_point",
        "external_anchor_no_replace_publication",
        "external_anchor_hardlink_alias_recovery",
        "external_lock_acquired_before_target_inspection",
        "external_product_handoff_to_target_anchor",
        "external_lock_not_exposed_to_child_env",
        "persistent_external_flock_anchors",
        "control_root_stays_writable_while_locked",
        "target_anchor_lock_held_through_launch_child",
        "same_canonical_target_serialized",
        "different_canonical_targets_concurrent_after_handoff",
        "concurrent_setup_mutations_denied_while_launching",
        "legacy_sibling_backups_read_only_when_strictly_validated",
        "restore_validates_backup_envelope_before_mutation",
        "restore_validates_stamp_path_set_and_digests",
        "backup_entry_payload_size_sha256_validated",
        "backup_slot_replacement_transactional",
        "failed_mutation_removes_new_backup",
        "restore_post_validates_clean_state",
        "restore_rollback_byte_identical_on_failure",
        "same_setup_profile_noop",
        "setup_update_uses_installed_identity",
        "postconditions_compare_intended_bytes",
        "post_replace_failure_rolls_back",
        "object_preserving_rollback",
        "software_no_target_stage_or_rollback_dirs",
        "supported_host_preflight_before_target_resolution",
        "installer_fetch_errors_are_domain_errors",
        "launch_requires_current_target_owned_software",
        "launch_uses_verified_private_image",
        "launch_image_regular_immutable_mode",
        "runtime_home_tmp_xdg_stay_writable_while_locked",
        "launch_denies_lifecycle_auth_plugin_marketplace_mcp_mutations",
    ):
        if safety.get(key) is not True:
            raise ValueError(f"contract safety must set {key}=true")
    if safety.get("external_bootstrap_product_anchor") != "global.lock":
        raise ValueError("contract safety product anchor mismatch")
    if safety.get("external_bootstrap_target_anchor_root") != "target-locks":
        raise ValueError("contract safety target anchor root mismatch")
    if safety.get("external_anchor_final_unlinked_on_recovery") is not False:
        raise ValueError("contract safety must never unlink final anchors during recovery")
    if safety.get("external_read_only_cold_no_anchor_creates_lock") is not False:
        raise ValueError("contract safety cold read-only path must create no anchors")
    if safety.get("external_read_only_cold_no_anchor_post_observation_retry") is not True:
        raise ValueError("contract safety cold read-only path must retry after anchor publication")
    if safety.get("external_read_only_seeded_uses_product_coordination") is not True:
        raise ValueError("contract safety seeded read-only path mismatch")
    if safety.get("target_local_lock_created") is not False:
        raise ValueError("contract safety must declare no target-local lock creation")
    if safety.get("atomic_write_order") != (
        "temporary write, temporary mode, file fsync, replace, parent fsync"
    ):
        raise ValueError("contract atomic write order mismatch")
    if "same user" not in str(safety.get("same_uid_malicious_mutation_boundary", "")).replace(
        "-", " "
    ):
        raise ValueError("contract must document the same-user mutation boundary")
    if "sandbox off" not in str(safety.get("same_uid_malicious_mutation_boundary", "")).replace(
        "-", " "
    ):
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
    if baseline.get("product", {}).get("official_docs_url") != "https://docs.x.ai/build/overview":
        raise ValueError("baseline official docs URL must use the live build overview")
    if "getting-started" in json.dumps(baseline.get("official_sources", [])):
        raise ValueError("baseline official sources must not reference dead getting-started docs")
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
    blocked_platform = "win" + "dows"
    if blocked_platform in json.dumps(runtime.get("supported_platforms", [])).lower():
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
    if "remove-cli" not in str(lifecycle.get("remove_command", "")):
        raise ValueError("software_lifecycle remove_command must expose remove-cli")
    if "unrelated" not in str(lifecycle.get("remove_precondition", "")):
        raise ValueError("software_lifecycle remove_precondition must preserve unrelated state")
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
    if "remove-cli" not in str(manifest_lifecycle.get("remove_command", "")):
        raise ValueError("manifest software lifecycle must expose remove-cli")
    validate_manager_source()
    validate_public_documented_commands()
    if args.network_observation:
        validate_network_observations(contract, baseline)
    manager = load_manager_module()
    validate_json_argparse_errors(manager)
    validate_platform_scope(manager, manifest, contract, baseline)
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
