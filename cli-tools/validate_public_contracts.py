#!/usr/bin/env python3
"""Validate static public artifacts for nddev-grok-build-app."""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
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
    "actionlint.yml",
    "codeql.yml",
    "dependency-review.yml",
    "release.yml",
    "scorecard.yml",
    "secret-scan.yml",
    "zizmor.yml",
}
FORBIDDEN_RAW_OBSERVATION_FIELDS = {
    "observed_at",
    "pushed_at",
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
GDS_ENTRIES = {"bundle.lock.yaml", "compiled-policy.json", "repository.yaml"}
GDS_PROJECTIONS = (".claude/CLAUDE.md", ".gds/compiled-policy.json", "AGENTS.md")
SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
SOURCE_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
SOURCE_TREE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


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


def _regular_file(path: Path) -> bool:
    mode = path.lstat().st_mode
    return stat.S_ISREG(mode) and not stat.S_ISLNK(mode) and stat.S_IMODE(mode) in {0o644, 0o755}


def validate_gds_contract() -> None:
    gds = ROOT / ".gds"
    require(
        stat.S_ISDIR(gds.lstat().st_mode) and not stat.S_ISLNK(gds.lstat().st_mode),
        ".gds must be a real directory",
    )
    require(
        {item.name for item in gds.iterdir()} == GDS_ENTRIES,
        ".gds directory entries mismatch",
    )
    for name in GDS_ENTRIES:
        require(
            _regular_file(gds / name),
            f".gds/{name} must be a tracked-style regular file",
        )

    repository = (gds / "repository.yaml").read_text(encoding="utf-8").splitlines()
    agent_headers = [
        line
        for line in repository
        if re.match(r"""^\s*(?:"agent"|'agent'|agent)\s*:\s*(?:#.*)?$""", line)
    ]
    require(
        agent_headers == ["agent:"],
        "repository must contain exactly one canonical agent section",
    )
    agent_lookalikes = [
        line
        for line in repository
        if re.match(r"""^(?:"agent[-_][^"]*"|'agent[-_][^']*'|agent[-_][^\s:]*)\s*:""", line)
    ]
    require(not agent_lookalikes, "repository contains an agent managed-key lookalike")
    require(
        sum(
            re.match(r"""^\s*["']?generated_agents["']?\s*:""", line) is not None
            for line in repository
        )
        == 1,
        "generated_agents must occur exactly once globally",
    )
    generated_lookalikes = [
        line
        for line in repository
        if re.match(r"""^\s*["']?generated[-_]agents[^"'\s:]*["']?\s*:""", line)
    ]
    require(
        generated_lookalikes == ["  generated_agents: true"],
        "generated_agents lookalike or noncanonical key",
    )
    agent_start = repository.index("agent:")
    agent_end = next(
        (
            i
            for i in range(agent_start + 1, len(repository))
            if repository[i] and not repository[i].startswith(" ")
        ),
        len(repository),
    )
    generated = [
        line.split(": ", 1)[1]
        for line in repository[agent_start + 1 : agent_end]
        if line.startswith("  generated_agents: ")
    ]
    require(
        generated == ["true"],
        "agent.generated_agents must occur exactly once and be true",
    )

    lines = (gds / "bundle.lock.yaml").read_text(encoding="utf-8").splitlines()
    require(
        lines[:3] == ["# GENERATED FILE - DO NOT EDIT DIRECTLY", "schema_version: 1", ""],
        "bundle lock header/schema mismatch",
    )
    require(
        sum(re.match(r"""^\s*["']?schema_version["']?\s*:""", line) is not None for line in lines)
        == 1,
        "duplicate schema_version",
    )
    top = [line[:-1] for line in lines if line and not line.startswith(" ") and line.endswith(":")]
    require(top == ["bundle", "projection"], "bundle lock top-level sections mismatch")
    bundle_start = lines.index("bundle:")
    projection_start = lines.index("projection:")
    require(bundle_start == 3, "unexpected content before bundle section")
    bundle = lines[bundle_start + 1 : projection_start]
    require(
        sum(
            re.match(
                r"""^\s*["']?(?:source_tree_digest|source_commit)["']?\s*:""",
                line,
            )
            is not None
            for line in lines
        )
        == 1,
        "bundle source identity must occur exactly once globally",
    )
    require(
        sum(re.match(r"""^\s*["']?output_digest["']?\s*:""", line) is not None for line in lines)
        == 1,
        "output_digest must occur exactly once globally",
    )
    require(
        sum(re.match(r"""^\s*["']?files["']?\s*:""", line) is not None for line in lines) == 1,
        "files must occur exactly once globally",
    )
    require(
        [line.split(":", 1)[0].strip() for line in bundle if line]
        in (
            ["version", "release_sequence", "channel", "source_tree_digest", "digest"],
            ["version", "release_sequence", "channel", "source_commit", "digest"],
        ),
        "bundle keys mismatch",
    )
    require(
        all(
            re.match(r"^  [a-z_]+: (?:\"[^\"]*\"|[0-9]+)$", line) is not None
            for line in bundle
            if line
        ),
        "bundle key serialization mismatch",
    )
    source_lines = [
        line
        for line in bundle
        if line.startswith("  source_tree_digest: ") or line.startswith("  source_commit: ")
    ]
    require(len(source_lines) == 1, "bundle source identity missing or duplicated")
    source_key, source_raw = source_lines[0].split(": ", 1)
    source = json.loads(source_raw)
    pattern = SOURCE_TREE_DIGEST if source_key.strip() == "source_tree_digest" else SOURCE_COMMIT
    require(
        isinstance(source, str) and pattern.fullmatch(source) is not None,
        "bundle source identity format mismatch",
    )
    files_index = lines.index("  files:", projection_start + 1)
    projection_head = lines[projection_start + 1 : files_index]
    require(
        [line.split(":", 1)[0].strip() for line in projection_head if line]
        == ["input_digest", "output_digest"],
        "projection keys mismatch",
    )
    require(
        all(
            re.match(r"^  [a-z_]+: \"[^\"]*\"$", line) is not None
            for line in projection_head
            if line
        ),
        "projection key serialization mismatch",
    )
    output = json.loads(projection_head[1].split(": ", 1)[1])
    require(
        isinstance(output, str) and SHA256.fullmatch(output) is not None,
        "projection.output_digest format mismatch",
    )
    entries: list[dict[str, str]] = []
    tail = lines[files_index + 1 :]
    require(len(tail) == 2 * len(GDS_PROJECTIONS), "projection.files shape mismatch")
    for index in range(0, len(tail), 2):
        require(
            tail[index].startswith('    - path: "')
            and tail[index + 1].startswith('      digest: "'),
            "projection.files indentation/shape mismatch",
        )
        relative = json.loads(tail[index].split(": ", 1)[1])
        digest = json.loads(tail[index + 1].split(": ", 1)[1])
        require(
            isinstance(relative, str)
            and isinstance(digest, str)
            and SHA256.fullmatch(digest) is not None,
            "projection file entry invalid",
        )
        entries.append({"path": relative, "digest": digest})
    require(
        tuple(entry["path"] for entry in entries) == GDS_PROJECTIONS,
        "projection paths/order mismatch",
    )
    encoded = json.dumps(
        entries, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    require(
        output == f"sha256:{hashlib.sha256(encoded).hexdigest()}",
        "projection aggregate digest mismatch",
    )
    for entry in entries:
        projection = ROOT / entry["path"]
        require(
            _regular_file(projection),
            f"managed projection is not a regular file: {entry['path']}",
        )
        require(
            entry["digest"] == f"sha256:{hashlib.sha256(projection.read_bytes()).hexdigest()}",
            f"managed projection digest mismatch: {entry['path']}",
        )
    workflow = (ROOT / "release/package.yml").read_text(encoding="utf-8")

    def closure(name: str) -> set[str]:
        match = re.search(rf"(?m)^{name}: >-\n((?:  .+\n?)+)", workflow)
        require(match is not None, f"release workflow missing {name}")
        return set(match.group(1).split())

    require(".gds" in closure("archive_paths"), "release archive_paths must include .gds")
    require(
        ".gds" not in closure("runtime_paths"),
        "release runtime_paths must exclude .gds",
    )


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
    require(
        contract["software_lifecycle"]["version"] == runtime,
        "contract runtime mismatch",
    )
    require(
        manifest["software_lifecycle"]["version"] == runtime,
        "manifest runtime mismatch",
    )
    require(contract.get("version_ref") == "build/version.json", "version_ref mismatch")
    require(contract.get("manifest_ref") == "build/manifest.json", "manifest_ref mismatch")
    return manifest, contract, baseline


def validate_catalog(manifest: dict[str, Any], contract: dict[str, Any]) -> None:
    require(manifest.get("setup_ids") == SETUPS, "manifest setup ids mismatch")
    require(manifest.get("profile_ids") == PROFILES, "manifest profile ids mismatch")
    require(contract["setup_system"]["setup_ids"] == SETUPS, "contract setup ids mismatch")
    require(
        contract["setup_system"]["profile_ids"] == PROFILES,
        "contract profile ids mismatch",
    )
    require(manifest.get("default_setup") == "nddev-builder", "default setup mismatch")
    require(manifest.get("default_profile") == "full-auto", "default profile mismatch")
    setup = load_json("setups/nddev-builder/setup.json")
    require(setup.get("id") == "nddev-builder", "setup id mismatch")
    native = setup.get("native_marketplace")
    require(isinstance(native, dict), "native marketplace projection missing")
    for key in ("source_path", "plugin_source_path"):
        relative = native.get(key)
        require(
            isinstance(relative, str) and (ROOT / relative).exists(),
            f"missing native marketplace source {key}",
        )
    for profile_id in PROFILES:
        profile = load_json(f"profiles/{profile_id}/profile.json")
        require(profile.get("id") == profile_id, f"profile id mismatch: {profile_id}")
    managed = manifest.get("managed_files")
    require(
        isinstance(managed, list) and len(managed) == len(set(managed)),
        "managed projection invalid",
    )
    require(contract["managed_state"]["stamp_file"] in managed, "managed stamp missing")


def validate_marketplace(version: str) -> None:
    marketplace = load_json("builder/nddev-builder/.grok-plugin/marketplace.json")
    index = load_json("builder/nddev-builder/.grok-plugin/plugin-index.json")
    plugin = load_json("builder/nddev-builder/plugins/nddev-builder/plugin.json")
    entries = marketplace.get("plugins")
    require(isinstance(entries, list) and len(entries) == 1, "marketplace entry invalid")
    require(entries[0].get("name") == "nddev-builder", "marketplace plugin id mismatch")
    require(entries[0].get("version") == version, "marketplace plugin version mismatch")
    require(
        entries[0].get("source") == {"type": "local", "path": "../plugins/nddev-builder"},
        "marketplace local source mismatch",
    )
    require(plugin.get("name") == "nddev-builder", "plugin name mismatch")
    require(plugin.get("version") == version, "plugin version mismatch")
    components = index.get("plugins", {}).get("nddev-builder", {}).get("components", {})
    skills = components.get("skills")
    require(isinstance(skills, list) and skills, "plugin index skills missing")
    skill_root = ROOT / "builder/nddev-builder/plugins/nddev-builder/skills"
    require(
        {item["name"] for item in skills} == {path.name for path in skill_root.iterdir()},
        "plugin index skill projection mismatch",
    )


def validate_runtime_integrity(
    manifest: dict[str, Any], contract: dict[str, Any], baseline: dict[str, Any]
) -> None:
    lifecycle = contract["software_lifecycle"]
    manifest_lifecycle = manifest["software_lifecycle"]
    for key in (
        "version",
        "channel",
        "install_mechanism",
        "npm_package",
        "npm_integrity",
        "npm_shasum",
        "npm_tarball",
        "native_npm_packages",
        "archive_policy",
    ):
        require(
            lifecycle[key] == manifest_lifecycle[key],
            f"software lifecycle {key} mismatch",
        )
    require(
        lifecycle["native_npm_packages"] == baseline["release"]["native_npm_package_mapping"],
        "native npm package ledger mismatch",
    )
    require(
        set(lifecycle["native_npm_packages"]) == set(SUPPORTED),
        "native package host scope mismatch",
    )
    for host, package in lifecycle["native_npm_packages"].items():
        require(
            host in SUPPORTED and package.get("product_supported") is True,
            f"unsupported native package {host}",
        )
        integrity = package.get("integrity")
        require(
            isinstance(integrity, str) and integrity.startswith("sha512-"),
            f"invalid integrity for {host}",
        )
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
    for marker in (
        "NDDEV_GROK_BUILD_TEST",
        "BOOTSTRAP_ROOT_OVERRIDE",
        "TEST_INSTALLER",
        "FAIL_AFTER",
    ):
        require(marker not in source, f"public manager contains test marker {marker}")
    for marker in FORBIDDEN_RAW_MANAGER_MARKERS:
        require(
            marker not in source,
            f"public manager contains raw observation marker {marker}",
        )


def validate_release_surface() -> None:
    agents = ROOT / "AGENTS.md"
    require(stat.S_ISREG(agents.lstat().st_mode), "AGENTS.md must be a regular file")
    require((ROOT / "release/package.yml").is_file(), "missing release package manifest")
    for relative in (
        "AGENTS.md",
        "CHANGELOG.md",
        "LICENSE",
        "README.md",
        "VERSION",
        "build",
        "builder",
        "cli-tools",
        "config",
        "docs",
        "profiles",
        "references",
        "setups",
    ):
        require((ROOT / relative).exists(), f"missing release path {relative}")
    bridge_root = ROOT / ".claude"
    bridge = bridge_root / "CLAUDE.md"
    require(
        stat.S_ISDIR(bridge_root.lstat().st_mode),
        "Claude bridge root must be a directory",
    )
    require(
        sorted(path.name for path in bridge_root.iterdir()) == ["CLAUDE.md"],
        "Claude bridge directory must contain only CLAUDE.md",
    )
    require(stat.S_ISREG(bridge.lstat().st_mode), "Claude bridge must be a regular file")
    require(bridge.read_bytes() == b"@../AGENTS.md\n", "Claude bridge mismatch")
    workflows = ROOT / ".github" / "workflows"
    require(workflows.is_dir(), "required release-check workflow directory is missing")
    workflow_files = {path.name for path in workflows.iterdir() if path.is_file()}
    require(
        workflow_files == {"test.yml"},
        "public repository may contain only the release-check test.yml workflow",
    )
    if workflow_files == {"test.yml"}:
        workflow = (workflows / "test.yml").read_text(encoding="utf-8")
        for fragment in (
            "permissions:\n  contents: read",
            "runs-on: ubuntu-24.04",
            "name: test",
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
            "run: python3 cli-tools/validate_public_contracts.py",
        ):
            require(
                fragment in workflow,
                f"test.yml is missing required release-check fragment: {fragment!r}",
            )
        require(
            "pull_request_target" not in workflow and "${{ secrets" not in workflow,
            "test.yml may not use privileged PR triggers or repository secrets",
        )


def validate_provider_protocol(manifest: dict[str, Any], contract: dict[str, Any]) -> None:
    require(
        stat.S_IMODE((ROOT / "cli-tools/nddev_grok_build.py").stat().st_mode) == 0o755,
        "provider manager must be executable with mode 0755",
    )
    expected_commands = [
        "provider-info",
        "validate-bundle",
        "plan-operation",
        "apply-operation",
        "recover-operation",
        "status",
    ]
    expected_operations = ["backup", "install", "remove", "replace", "restore"]
    for label, document in (("manifest", manifest), ("contract", contract)):
        provider = document.get("provider_protocol")
        require(isinstance(provider, dict), f"{label} provider protocol missing")
        require(provider.get("version") == 3, f"{label} provider version mismatch")
        require(
            provider.get("bundle_format") == "ai-stp-bundle/1",
            f"{label} bundle mismatch",
        )
        require(
            provider.get("commands") == expected_commands,
            f"{label} provider commands mismatch",
        )
        require(
            provider.get("operations") == expected_operations,
            f"{label} provider operations mismatch",
        )
    for relative in (
        "cli-tools/provider_protocol_v3.py",
        "cli-tools/provider_runtime_v3.py",
    ):
        require(_regular_file(ROOT / relative), f"provider runtime file missing: {relative}")


def main(argv: list[str] | None = None) -> int:
    parse_args(argv)
    try:
        manifest, contract, baseline = validate_versions()
        validate_catalog(manifest, contract)
        validate_marketplace((ROOT / "VERSION").read_text(encoding="utf-8").strip())
        validate_runtime_integrity(manifest, contract, baseline)
        validate_static_source()
        validate_provider_protocol(manifest, contract)
        validate_gds_contract()
        validate_release_surface()
    except Exception as exc:
        print(f"validate_public_contracts.py: FAIL: {exc}", file=sys.stderr)
        return 1
    print("validate_public_contracts.py: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
