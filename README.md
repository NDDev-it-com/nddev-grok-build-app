# nddev-grok-build-app

Portable setup manager for the current xAI Grok Build terminal agent.

This module manages an explicit, absolute Grok Build home. It never defaults to
live `~/.grok`, never invokes live Grok Build during setup/profile switching,
and preserves unmanaged state in the target.

## Commands

```bash
python3 cli-tools/nddev_grok_build.py list --json
python3 cli-tools/nddev_grok_build.py status --target /absolute/grok-home --json
python3 cli-tools/nddev_grok_build.py plan --target /absolute/grok-home --json
python3 cli-tools/nddev_grok_build.py install --target /absolute/grok-home --json
python3 cli-tools/nddev_grok_build.py switch --target /absolute/grok-home --profile safe --json
python3 cli-tools/nddev_grok_build.py migrate --target /absolute/grok-home --profile full-auto --json
python3 cli-tools/nddev_grok_build.py restore --backup 0 --target /absolute/grok-home --json
python3 cli-tools/nddev_grok_build.py remove --target /absolute/grok-home --json
python3 cli-tools/nddev_grok_build.py software-status --target /absolute/grok-home --json
python3 cli-tools/nddev_grok_build.py install-cli --target /absolute/grok-home --json
python3 cli-tools/nddev_grok_build.py update-cli --target /absolute/grok-home --json
python3 cli-tools/nddev_grok_build.py launch --target /absolute/grok-home -- -p "Explain this repo"
```

`install-cli` and `update-cli` install target-owned Grok Build through the
official stable-channel vendor installer with an exact version argument and
SHA-256 verification. The current version, npm integrity, installer URL, and
hash are code-owned in `build/version.json`,
`references/grok-build-baseline.json`, and `cli-tools/nddev_grok_build.py`.

## Setup And Profiles

The content setup is `nddev-builder`. It enables maximum documented builder
capabilities inside the isolated managed `GROK_HOME`: memory, subagents, web
fetch, LSP tools, file writes, tool search, native skills, native plugins, and a
target-local Grok marketplace. It also disables Grok config auto-update and
envrc loading for the pinned runtime.

Permission profiles are orthogonal:

- `full-auto`: native `always-approve`, sandbox `off`, no managed permission
  deny rules.
- `safe`: native `ask`, sandbox `strict`.

Legacy schema-1 setup ids `safe`, `balanced`, and `full-auto` are readable for
status, migration, restore, and removal only. Legacy state is never launchable.

## Builder Toolkit

The public NDDev Builder toolkit lives under
`builder/nddev-builder/plugins/nddev-builder`. The manager projects the full
regular-file toolkit into:

- `$GROK_HOME/skills/`
- `$GROK_HOME/agents/`
- `$GROK_HOME/plugins/nddev-builder/`
- `$GROK_HOME/plugins/marketplaces/nddev-builder/`

The local marketplace manifest is
`builder/nddev-builder/.grok-plugin/marketplace.json`; its plugin source is a
relative path to the sibling plugin tree. Plugins and marketplaces deliver Grok
content files only, not native binaries or external runtimes.

## Launch Boundary

`launch` executes only the target-owned `<target>/bin/grok` with
`GROK_HOME=<target>`, target-local child `HOME` and `TMPDIR`, auto-updates
disabled, and provider credentials stripped from the inherited environment. It
rejects Grok Build flags that override managed target, session, model,
permission, sandbox, tool, plugin, cwd, or system-prompt scope and never falls
back to `PATH`.
