---
name: grok-skills-instructions
description: Create or review Grok Build skills and instruction files. Use for SKILL.md, AGENTS.md, .grok/rules, and routing metadata.
license: AGPL-3.0-or-later
---

# Grok Skills And Instructions

Use instructions for broad repository behavior and skills for repeatable
task-specific procedures.

Instruction discovery:

- `$GROK_HOME/AGENTS.md`
- `AGENTS.md`, `Agents.md`, `AGENT.md` along the working tree
- `.grok/rules/*.md`

Skill discovery:

- `.grok/skills/<name>/SKILL.md`
- `$GROK_HOME/skills/<name>/SKILL.md`
- plugin `skills/<name>/SKILL.md`
- configured `[skills].paths`

Skill frontmatter must include a precise `name` and `description`. Use
`when-to-use`, `allowed-tools`, `argument-hint`, `user-invocable`, and
`disable-model-invocation` only when they clarify routing or execution.
Focused skills should reference local `references/` files instead of embedding
long volatile tables.
