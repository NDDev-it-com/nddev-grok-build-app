#!/usr/bin/env python3
"""Validate public nddev-grok-build-app release contracts."""

from __future__ import annotations

import argparse
import importlib.util
import json
import stat
import sys
from pathlib import Path
from typing import Any

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
SOFTWARE_LIFECYCLE_KEYS = {
    "channel",
    "command",
    "credential_inheritance",
    "discarded_stage_paths",
    "entrypoint",
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    return parser.parse_args(argv)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


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
    validate_workflows()
    print("validate_public_contracts.py: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"validate_public_contracts.py: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
