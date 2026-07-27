---
name: grok-hooks
description: Create or review Grok Build hooks. Use for hooks JSON, config hooks, events, trust, stdin/stdout contract, and fail-open behavior.
license: AGPL-3.0-or-later
---

# Grok Hooks

Hook files are JSON under `$GROK_HOME/hooks/*.json`, project
`.grok/hooks/*.json`, or plugin `hooks/hooks.json`. Hooks can also be declared
as TOML `[[hooks.<Event>]]` entries in config layers.

Use event names documented by Grok Build: `SessionStart`, `SessionEnd`,
`UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`,
`PermissionDenied`, `Stop`, `StopFailure`, `Notification`, `SubagentStart`,
`SubagentStop`, `PreCompact`, and `PostCompact`.

`PreToolUse` can deny a call by writing JSON to stdout. Hook failures are
fail-open except explicit deny/block decisions. Project hooks require folder
trust; plugin hooks require plugin trust.
