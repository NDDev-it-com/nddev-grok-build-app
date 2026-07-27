---
name: grok-agents-subagents
description: Create or review Grok Build agents, subagents, roles, personas, and MCP inheritance. Use for .grok/agents, agent frontmatter, subagents, roles, personas, and mcpInheritance.
license: AGPL-3.0-or-later
---

# Grok Agents And Subagents

Native agent files are Markdown under `.grok/agents/`, `$GROK_HOME/agents/`,
or plugin `agents/`.

Agent frontmatter uses camelCase. Common fields include `name`, `description`,
`tools`, `disallowedTools`, `permissionMode`, `capabilityMode`, `model`,
`effort`, `agentsMd`, `discoverSkills`, `inheritSkills`, and `mcpInheritance`.

Subagent built-ins are `general-purpose`, `explore`, and `plan`. Custom roles
can be declared under `[subagents.roles.<name>]` or `.grok/roles/*.toml`.
Personas can be declared under `[subagents.personas.<name>]` or
`.grok/personas/*.toml`.

`mcpInheritance` accepts `all`, `none`, `{ named: [...] }`, or
`{ except: [...] }`. Plugin agents cannot declare their own `mcpServers`, hooks,
or bypass-permissions mode.
