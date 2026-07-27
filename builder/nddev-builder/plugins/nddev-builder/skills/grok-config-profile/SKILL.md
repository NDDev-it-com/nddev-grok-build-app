---
name: grok-config-profile
description: Create or review Grok Build config ownership, setup/profile separation, and managed config.toml snippets. Use for config.toml, setup.json, profile.json, and ownership questions.
license: AGPL-3.0-or-later
---

# Grok Config And Profiles

Use `setups/<id>/setup.json` for content policy and `profiles/<id>/profile.json`
for permission policy. Do not mix them.

Native config locations:

- User: `$GROK_HOME/config.toml`
- Project: `.grok/config.toml`
- Managed: `$GROK_HOME/managed_config.toml`, `/etc/grok/managed_config.toml`
- Requirements: `$GROK_HOME/requirements.toml`, `/etc/grok/requirements.toml`

Project `.grok/config.toml` is limited to `[mcp_servers]`, `[plugins]`, and
`[permission]`. User config may carry builder-owned `[features]`, `[memory]`,
`[subagents]`, `[cli]`, `[session]`, `[plugins]`, and `[[marketplace.sources]]`.

For exact public versions, pins, and generated managed paths, point to
`build/version.json`, `config/nddev-contract.json`, and
`cli-tools/nddev_grok_build.py`.
