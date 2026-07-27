# Grok Build Native Surfaces

Use these native surfaces only:

- Instructions: `AGENTS.md`, `Agents.md`, `AGENT.md`, `.grok/rules/*.md`.
- Skills: `.grok/skills/<name>/SKILL.md`, `$GROK_HOME/skills/<name>/SKILL.md`, plugin `skills/<name>/SKILL.md`.
- Agents: `.grok/agents/*.md`, `$GROK_HOME/agents/*.md`, plugin `agents/*.md`.
- Personas and roles: `.grok/personas/*.toml`, `$GROK_HOME/personas/*.toml`, `.grok/roles/*.toml`, `[subagents.roles.*]`, `[subagents.personas.*]`.
- Plugins: `.grok/plugins/`, `$GROK_HOME/plugins/`, `[plugins].paths`, `--plugin-dir`.
- Marketplaces: `.grok-plugin/marketplace.json`, optional `.grok-plugin/plugin-index.json`, `[[marketplace.sources]]`.
- Hooks: `$GROK_HOME/hooks/*.json`, `.grok/hooks/*.json`, config `[[hooks.<Event>]]`, plugin `hooks/hooks.json`.
- MCP: `[mcp_servers.<name>]`, project `.grok/config.toml`, plugin `.mcp.json`.
- Runtime manager facts: `cli-tools/nddev_grok_build.py`.

Plugins and marketplaces are content distribution surfaces. They do not install
native binaries, package managers, or external runtimes.
