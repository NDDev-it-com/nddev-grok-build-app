---
name: grok-mcp
description: Create or review Grok Build MCP server configuration. Use for [mcp_servers], .mcp.json, stdio, HTTP/SSE, OAuth, env expansion, and tool naming.
license: AGPL-3.0-or-later
---

# Grok MCP

Declare MCP servers in `[mcp_servers.<name>]` in `$GROK_HOME/config.toml` or
project `.grok/config.toml`. Plugins may ship `.mcp.json`.

Stdio transport uses `command`, `args`, `env`, and optional `cwd`. HTTP/SSE
transport uses `url`, optional `headers`, `bearer_token_env_var`, OAuth client
fields, and timeouts. Secrets should be referenced through environment
variables such as `${TOKEN}` rather than committed inline.

MCP tools are namespaced as `<server>__<tool>`. Subagents inherit connected MCP
servers by default unless `mcpInheritance` restricts them.
