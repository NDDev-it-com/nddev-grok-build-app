---
name: grok-creator-checker-release
description: Create, check, and prepare public Grok Build artifacts for release validation. Use for creator/checker workflows, public contract checks, and release readiness without private harness evidence.
license: AGPL-3.0-or-later
---

# Grok Creator Checker Release

Creator workflow:

1. Pick the native surface: config/profile, permission/sandbox, skill,
   instruction, agent/subagent, plugin/marketplace, hook, MCP, or lifecycle.
2. Use the focused skill for that surface.
3. Keep volatile versions, pins, and enumerations in code-owned public files.
4. Keep private tests, memories, and evidence outside this public module.

Checker workflow:

1. Verify every referenced path exists.
2. Verify local marketplace sources resolve to an existing plugin directory.
3. Verify plugin and marketplace payloads contain regular content files only.
4. Verify generated setup/profile config is orthogonal.
5. Run the public validation commands in `nddev-builder/references/validation-workflows.md`.

Release validation here is public-module validation only. Root-private harness
release evidence and registry pin advancement happen later in the private
control plane.
