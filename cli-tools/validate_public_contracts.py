#!/usr/bin/env python3
"""Validate public nddev-grok-build-app release contracts."""

from __future__ import annotations

import argparse
import json
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
SETUP_ORDER = ["safe", "balanced", "full-auto"]
GROK_VERSION = "0.2.112"
INSTALLER_URL = "https://x.ai/cli/install.sh"
INSTALLER_SHA256 = "0465d810453bbf18608ccae310fa79f4c59ae4a0538bd8a3a374ebce749be952"
SOFTWARE_LIFECYCLE_KEYS = {
    "command",
    "credential_inheritance",
    "discarded_stage_paths",
    "entrypoint",
    "install_command",
    "install_precondition",
    "installer_sha256",
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
        if setup.get("nddev_builder_default") is not True:
            raise ValueError(f"{setup_json}: nddev-builder must be default-on")
    return ids


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
    if version != "0.1.0":
        raise ValueError("VERSION must be 0.1.0")
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
    if build.get("grok_build_tested") != baseline["release"]["npm_version"]:
        raise ValueError("tested Grok Build version differs from baseline release")
    if build.get("grok_build_tested") != GROK_VERSION:
        raise ValueError("tested Grok Build version must be 0.2.112")
    if baseline["runtime"]["command"] != "grok":
        raise ValueError("baseline command must be grok")
    if baseline["release"].get("official_installer") != INSTALLER_URL:
        raise ValueError("baseline must pin the official vendor installer")
    if baseline["release"].get("official_installer_sha256") != INSTALLER_SHA256:
        raise ValueError("baseline installer SHA-256 mismatch")
    if baseline["release"].get("module_install_mechanism") != "vendor-installer-only":
        raise ValueError("baseline must declare vendor-installer-only install")
    if baseline["release"].get("module_npm_install_supported") is not False:
        raise ValueError("module must not support npm installation")
    if contract["plugin_marketplace"]["external_marketplace_published"] is not None:
        raise ValueError("external marketplace must remain null until published")
    runtime = contract.get("runtime_launch", {})
    if runtime.get("managed_command") != "bin/grok":
        raise ValueError("runtime launch must use target-owned bin/grok")
    if runtime.get("path_fallback") is not False:
        raise ValueError("runtime launch must disable PATH fallback")
    if runtime.get("requires_current_target_owned_software") is not True:
        raise ValueError("runtime launch must require current target-owned software")
    lifecycle = contract.get("software_lifecycle")
    if not isinstance(lifecycle, dict) or set(lifecycle) != SOFTWARE_LIFECYCLE_KEYS:
        raise ValueError("contract software_lifecycle keys mismatch")
    if lifecycle.get("official_installer") != INSTALLER_URL:
        raise ValueError("software_lifecycle official installer mismatch")
    if lifecycle.get("installer_sha256") != INSTALLER_SHA256:
        raise ValueError("software_lifecycle installer SHA-256 mismatch")
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
    manifest_lifecycle = manifest.get("software_lifecycle")
    if not isinstance(manifest_lifecycle, dict):
        raise ValueError("manifest software_lifecycle missing")
    if manifest_lifecycle.get("installer_sha256") != INSTALLER_SHA256:
        raise ValueError("manifest installer SHA-256 mismatch")
    if manifest_lifecycle.get("version") != GROK_VERSION:
        raise ValueError("manifest software version mismatch")
    for relative in (
        "builder/nddev-builder/plugin.json",
        "builder/nddev-builder/skills/nddev-builder/SKILL.md",
        "builder/nddev-builder/agents/nddev-builder.md",
        "cli-tools/nddev_grok_build.py",
    ):
        if not (ROOT / relative).is_file():
            raise ValueError(f"missing required public path {relative}")
    validate_workflows()
    print("validate_public_contracts.py: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"validate_public_contracts.py: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
