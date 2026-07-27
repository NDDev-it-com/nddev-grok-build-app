---
name: grok-permissions-sandbox
description: Create or review Grok Build permission and sandbox profiles. Use for always-approve, ask, safe, full-auto, sandbox, allow, deny, and launch override policy.
license: AGPL-3.0-or-later
---

# Grok Permissions And Sandbox

Use native values only.

- Full auto profile: `[ui].permission_mode = "always-approve"` and `[sandbox].profile = "off"`.
- Safe profile: `[ui].permission_mode = "ask"` and `[sandbox].profile = "strict"`.
- Do not add managed deny rules to full auto.
- Do not accept child launch flags that override target-owned permission,
  sandbox, model, system prompt, tools, plugin, cwd, or session scope.

Sandbox profiles are permission-independent. A permission approval decides
whether a tool call may run; the sandbox limits what an approved call can do.
Keep that boundary explicit in docs and generated config.
