#!/usr/bin/env python3
"""Validate static public artifacts for nddev-grok-build-app."""

from __future__ import annotations

import argparse
import ast
import base64
import json
import re
import stat
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\Z")
SETUPS = ["nddev-builder"]
PROFILES = ["full-auto", "safe"]
SUPPORTED = ["macos-arm64", "macos-x64", "ubuntu-glibc-arm64", "ubuntu-glibc-x64"]
REQUIRED_WORKFLOWS = {
    "actionlint.yml", "codeql.yml", "dependency-review.yml", "release.yml",
    "scorecard.yml", "secret-scan.yml", "zizmor.yml",
}
FORBIDDEN_RAW_OBSERVATION_FIELDS = {
    "observed_at",
    "npm_dist_tags",
    "npm_published_at",
    "alpha_channel_version",
    "enterprise_channel_version",
    "official_installer_assets",
    "product_unsupported_vendor_observations",
    "npm_package_distinction",
    "npm_platform_package_ids_observed",
}
FORBIDDEN_RAW_MANAGER_MARKERS = {
    "NPM_UNSUPPORTED_NATIVE_PACKAGE_OBSERVATIONS",
    "VENDOR_UNSUPPORTED_WINDOWS_ASSET_BY_ARCH",
}
FORBIDDEN_RAW_TREE_PATTERNS = (
    re.compile(r"@xai-official/grok-win32-(?:x64|arm64)"),
    re.compile(r"grok-\d+\.\d+\.\d+-windows-(?:x86_64|aarch64)\.exe"),
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    return parser.parse_args(argv)


def load_json(relative: str) -> dict[str, Any]:
    value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{relative} must contain a JSON object")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_versions() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    build = load_json("build/version.json")
    manifest = load_json("build/manifest.json")
    contract = load_json("config/nddev-contract.json")
    baseline = load_json("references/grok-build-baseline.json")
    require(bool(SEMVER.fullmatch(version)), "VERSION must be semantic")
    require(build.get("build_version") == version, "build version mismatch")
    require(manifest.get("build_version") == version, "manifest version mismatch")
    runtime = build.get("grok_build_tested")
    require(runtime == baseline["release"]["npm_version"], "baseline runtime mismatch")
    require(contract["software_lifecycle"]["version"] == runtime, "contract runtime mismatch")
    require(manifest["software_lifecycle"]["version"] == runtime, "manifest runtime mismatch")
    require(contract.get("version_ref") == "build/version.json", "version_ref mismatch")
    require(contract.get("manifest_ref") == "build/manifest.json", "manifest_ref mismatch")
    return manifest, contract, baseline


def validate_catalog(manifest: dict[str, Any], contract: dict[str, Any]) -> None:
    require(manifest.get("setup_ids") == SETUPS, "manifest setup ids mismatch")
    require(manifest.get("profile_ids") == PROFILES, "manifest profile ids mismatch")
    require(contract["setup_system"]["setup_ids"] == SETUPS, "contract setup ids mismatch")
    require(contract["setup_system"]["profile_ids"] == PROFILES, "contract profile ids mismatch")
    require(manifest.get("default_setup") == "nddev-builder", "default setup mismatch")
    require(manifest.get("default_profile") == "full-auto", "default profile mismatch")
    setup = load_json("setups/nddev-builder/setup.json")
    require(setup.get("id") == "nddev-builder", "setup id mismatch")
    native = setup.get("native_marketplace")
    require(isinstance(native, dict), "native marketplace projection missing")
    for key in ("source_path", "plugin_source_path"):
        relative = native.get(key)
        require(isinstance(relative, str) and (ROOT / relative).exists(),
                f"missing native marketplace source {key}")
    for profile_id in PROFILES:
        profile = load_json(f"profiles/{profile_id}/profile.json")
        require(profile.get("id") == profile_id, f"profile id mismatch: {profile_id}")
    managed = manifest.get("managed_files")
    require(isinstance(managed, list) and len(managed) == len(set(managed)),
            "managed projection invalid")
    require(contract["managed_state"]["stamp_file"] in managed, "managed stamp missing")


def validate_marketplace(version: str) -> None:
    marketplace = load_json("builder/nddev-builder/.grok-plugin/marketplace.json")
    index = load_json("builder/nddev-builder/.grok-plugin/plugin-index.json")
    plugin = load_json("builder/nddev-builder/plugins/nddev-builder/plugin.json")
    entries = marketplace.get("plugins")
    require(isinstance(entries, list) and len(entries) == 1, "marketplace entry invalid")
    require(entries[0].get("name") == "nddev-builder", "marketplace plugin id mismatch")
    require(entries[0].get("version") == version, "marketplace plugin version mismatch")
    require(entries[0].get("source") == {"type": "local", "path": "../plugins/nddev-builder"},
            "marketplace local source mismatch")
    require(plugin.get("name") == "nddev-builder", "plugin name mismatch")
    require(plugin.get("version") == version, "plugin version mismatch")
    components = index.get("plugins", {}).get("nddev-builder", {}).get("components", {})
    skills = components.get("skills")
    require(isinstance(skills, list) and skills, "plugin index skills missing")
    skill_root = ROOT / "builder/nddev-builder/plugins/nddev-builder/skills"
    require({item["name"] for item in skills} == {path.name for path in skill_root.iterdir()},
            "plugin index skill projection mismatch")


def validate_runtime_integrity(
    manifest: dict[str, Any], contract: dict[str, Any], baseline: dict[str, Any]
) -> None:
    lifecycle = contract["software_lifecycle"]
    manifest_lifecycle = manifest["software_lifecycle"]
    for key in (
        "version", "channel", "install_mechanism", "npm_package", "npm_integrity",
        "npm_shasum", "npm_tarball", "native_npm_packages", "archive_policy",
    ):
        require(lifecycle[key] == manifest_lifecycle[key], f"software lifecycle {key} mismatch")
    require(lifecycle["native_npm_packages"] == baseline["release"]["native_npm_package_mapping"],
            "native npm package ledger mismatch")
    require(set(lifecycle["native_npm_packages"]) == set(SUPPORTED),
            "native package host scope mismatch")
    for host, package in lifecycle["native_npm_packages"].items():
        require(host in SUPPORTED and package.get("product_supported") is True,
                f"unsupported native package {host}")
        integrity = package.get("integrity")
        require(isinstance(integrity, str) and integrity.startswith("sha512-"),
                f"invalid integrity for {host}")
        base64.b64decode(integrity[7:], validate=True)
        shasum = package.get("shasum")
        require(isinstance(shasum, str) and len(shasum) == 40, f"invalid shasum for {host}")
        int(shasum, 16)
        require(package.get("unpacked_size", 0) > 0, f"invalid size for {host}")
    policy = lifecycle.get("archive_policy")
    require(policy.get("scripts_disabled") is True, "package scripts must remain disabled")
    require(policy.get("umbrella_expected_members"), "umbrella layout missing")
    require(policy.get("native_expected_members"), "native layout missing")
    observed_packages = baseline["release"].get("native_npm_packages")
    require(isinstance(observed_packages, dict), "native npm package catalog missing")
    supported_packages = {
        package["package"] for package in lifecycle["native_npm_packages"].values()
    }
    require(
        set(observed_packages) == supported_packages,
        "native npm package catalog must contain only supported packages",
    )
    require(
        all(package.get("product_supported") is True for package in observed_packages.values()),
        "native npm package catalog contains unsupported records",
    )
    for label, value in (
        ("manifest", manifest),
        ("contract", contract),
        ("baseline", baseline),
    ):
        serialized = json.dumps(value, sort_keys=True)
        for field in FORBIDDEN_RAW_OBSERVATION_FIELDS:
            require(
                f'"{field}"' not in serialized,
                f"{label} contains raw observation field {field}",
            )


def validate_static_source() -> None:
    path = ROOT / "cli-tools/nddev_grok_build.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    require({"parse_args", "main"} <= functions, "manager parse_args/main missing")
    for marker in ("NDDEV_GROK_BUILD_TEST", "BOOTSTRAP_ROOT_OVERRIDE", "TEST_INSTALLER",
                   "FAIL_AFTER"):
        require(marker not in source, f"public manager contains test marker {marker}")
    for marker in FORBIDDEN_RAW_MANAGER_MARKERS:
        require(marker not in source, f"public manager contains raw observation marker {marker}")


def validate_release_surface() -> None:
    agents = ROOT / "AGENTS.md"
    require(stat.S_ISREG(agents.lstat().st_mode), "AGENTS.md must be a regular file")
    for name in REQUIRED_WORKFLOWS:
        require((ROOT / ".github/workflows" / name).is_file(), f"missing workflow {name}")
    for relative in ("AGENTS.md", "CHANGELOG.md", "LICENSE", "README.md", "VERSION",
                     "build", "builder", "cli-tools", "config", "docs", "profiles",
                     "references", "setups"):
        require((ROOT / relative).exists(), f"missing release path {relative}")
    bridge_root = ROOT / ".claude"
    bridge = bridge_root / "CLAUDE.md"
    require(stat.S_ISDIR(bridge_root.lstat().st_mode), "Claude bridge root must be a directory")
    require(sorted(path.name for path in bridge_root.iterdir()) == ["CLAUDE.md"],
            "Claude bridge directory must contain only CLAUDE.md")
    require(stat.S_ISREG(bridge.lstat().st_mode), "Claude bridge must be a regular file")
    require(bridge.read_bytes() == b"@../AGENTS.md\n", "Claude bridge mismatch")


def validate_no_raw_observations() -> None:
    for path in ROOT.rglob("*"):
        if ".git" in path.parts or not path.is_file():
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in FORBIDDEN_RAW_TREE_PATTERNS:
            require(
                pattern.search(source) is None,
                f"{path.relative_to(ROOT)} contains raw unsupported vendor observation",
            )


def main(argv: list[str] | None = None) -> int:
    parse_args(argv)
    try:
        manifest, contract, baseline = validate_versions()
        validate_catalog(manifest, contract)
        validate_marketplace((ROOT / "VERSION").read_text(encoding="utf-8").strip())
        validate_runtime_integrity(manifest, contract, baseline)
        validate_static_source()
        validate_release_surface()
        validate_no_raw_observations()
    except Exception as exc:
        print(f"validate_public_contracts.py: FAIL: {exc}", file=sys.stderr)
        return 1
    print("validate_public_contracts.py: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
