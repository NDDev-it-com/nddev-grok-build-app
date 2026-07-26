---
name: nddev-builder
description: Build or review Grok Build-native artifacts. Use when creating or checking Grok skills, agents, hooks, MCP configuration, project rules, or plugin bundles.
license: AGPL-3.0-or-later
---

# NDDev Builder For Grok Build

Use only Grok Build-native surfaces that are documented by xAI:

1. Prefer `AGENTS.md` or `.grok/rules/*.md` for project instructions.
2. Use `.grok/skills/<name>/SKILL.md` or `$GROK_HOME/skills/<name>/SKILL.md` for skills.
3. Use `.grok/agents/*.md` or `$GROK_HOME/agents/*.md` for custom agents.
4. Use `$GROK_HOME/hooks/*.json`, `.grok/hooks/*.json`, or config-file hooks for hooks.
5. Use `[mcp_servers]` in `config.toml`, project `.grok/config.toml`, or plugin `.mcp.json` for MCP servers.
6. Package related skills, agents, hooks, and MCP config as a Grok plugin directory. Do not claim that plugins deliver external runtimes or native binaries.
7. Treat marketplace publishing as unsupported unless a real `.grok-plugin/marketplace.json` source and pinned plugin source are provided.

When checking an artifact, verify the configured scope, trust behavior, and whether the artifact runs code. Report unsupported or unverified capabilities as unsupported instead of inventing a compatibility layer.
