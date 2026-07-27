---
name: grok-plugins-marketplace
description: Create or review Grok Build plugins and native marketplaces. Use for plugin.json, .grok-plugin/marketplace.json, plugin-index.json, trust, and no-binary-delivery checks.
license: AGPL-3.0-or-later
---

# Grok Plugins And Marketplaces

A plugin directory may contain `plugin.json`, `skills/`, `commands/`, `agents/`,
`hooks/hooks.json`, `.mcp.json`, and `.lsp.json`.

A marketplace source has `.grok-plugin/marketplace.json` and may include
`.grok-plugin/plugin-index.json`. Local plugin sources in this module resolve
from the marketplace file directory, so use `../plugins/<name>` when
`marketplace.json` is inside `.grok-plugin/` and plugins are siblings.

Generated target layout:

- `$GROK_HOME/plugins/nddev-builder/`
- `$GROK_HOME/plugins/marketplaces/nddev-builder/.grok-plugin/marketplace.json`
- `$GROK_HOME/plugins/marketplaces/nddev-builder/plugins/nddev-builder/`
- `[plugins].enabled = ["nddev-builder"]`
- `[[marketplace.sources]]` points at the target-local marketplace root

Do not put native binaries, package managers, or external runtimes in plugin or
marketplace payloads.
