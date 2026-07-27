---
name: nddev-builder
description: Build or review Grok Build-native artifacts. Use when creating or checking Grok skills, agents, hooks, MCP configuration, project rules, marketplaces, or plugin bundles.
license: AGPL-3.0-or-later
---

# NDDev Builder For Grok Build

This is the routing skill for the public NDDev Grok Build toolkit. Use it to
select the narrow focused skill for the artifact being created or reviewed.

## Routing

- Configuration, setup/profile ownership, `config.toml`: use `grok-config-profile`.
- Permission modes, sandbox profiles, launch override boundaries: use `grok-permissions-sandbox`.
- Agents, subagents, roles, personas, MCP inheritance: use `grok-agents-subagents`.
- Skills and instruction files: use `grok-skills-instructions`.
- Plugins and native local marketplaces: use `grok-plugins-marketplace`.
- Hooks and trust behavior: use `grok-hooks`.
- MCP server declarations and discovery: use `grok-mcp`.
- Installer, target-owned runtime, migration, rollback: use `grok-install-lifecycle`.
- Creator/checker/release validation workflow: use `grok-creator-checker-release`.

## Rules

- Use only Grok Build-native surfaces documented by xAI.
- Do not invent a compatibility format when evidence is missing.
- Do not put private harness tests, memories, evidence, or root workflow material in this public plugin.
- Do not deliver native binaries or external runtimes through plugins or marketplaces.
- For volatile versions, pins, exact source URLs, and managed file enumerations, point to:
  `config/nddev-contract.json`, `build/version.json`,
  `references/grok-build-baseline.json`, and `cli-tools/nddev_grok_build.py`.

For exact native path families and validation commands, read
`references/native-surfaces.md` and `references/validation-workflows.md`.
